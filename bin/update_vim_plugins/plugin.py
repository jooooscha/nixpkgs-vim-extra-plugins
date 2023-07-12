import logging
import os
import urllib

import requests
from datetime import datetime, date
import jsonpickle
from datetime import datetime

from .nix import GitSource, License, Source, UrlSource
from .spec import PluginSpec, RepositoryHost


logger = logging.getLogger(__name__)


class VimPlugin:
    """Abstract base class for vim plugins."""

    name: str
    owner: str
    version: str
    source: Source
    description: str = "No description"
    homepage: str
    license: License
    source_line: str
    updated: date
    checked: date = datetime.now().date()

    def to_nix(self):
        """Return the nix expression for this plugin."""
        meta = f'with lib; {{ description = "{self.description}"; homepage = "{self.homepage}"; license = with licenses; [ {self.license.value} ]; }}'
        return f'{self.name} = buildVimPluginFrom2Nix {{ pname = "{self.name}"; version = "{self.version}"; src = {self.source.get_nix_expression()}; meta = {meta}; }};'

    def to_json(self):
        """Serizalize the plugin to json"""
        return jsonpickle.encode(self)

    def to_markdown(self):
        link = f"[{self.source_line}]({self.source.url})"
        updated = f"{self.updated}"
        package_name = f"{self.name}"
        checked = f"{self.checked}"

        return f"| {link} | {updated} | {package_name} | {checked} |"

    def __repr__(self):
        """Return the representation of this plugin."""
        return f"VimPlugin({self.name!r}, {self.version!r})"


def _get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token is None:
        logger.warning("GITHUB_TOKEN environment variable not set")
    return token


class GitHubPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a GitHubPlugin."""

        full_name = f"{plugin_spec.owner}/{plugin_spec.repo}"
        repo_info = self._api_call(f"repos/{full_name}")
        default_branch = plugin_spec.branch or repo_info["default_branch"]
        api_callback = self._api_call(f"repos/{full_name}/commits/{default_branch}")
        latest_commit = api_callback["commit"]
        sha = api_callback["sha"]

        self.name = plugin_spec.name
        self.owner = plugin_spec.owner
        self.version = latest_commit["committer"]["date"].split("T")[0]
        self.source = UrlSource(f"https://github.com/{full_name}/archive/{sha}.tar.gz")
        self.description = repo_info.get("description") or self.description
        self.homepage = repo_info["html_url"]
        self.license = plugin_spec.license or License.from_spdx_id((repo_info.get("license") or {}).get("spdx_id"))
        self.source_line = plugin_spec.line
        self.updated = datetime.strptime(latest_commit["committer"]["date"], '%Y-%m-%dT%H:%M:%SZ').date()

    def _api_call(self, path: str, token: str | None = _get_github_token()):
        """Call the GitHub API."""
        url = f"https://api.github.com/{path}"
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"token {token}"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"GitHub API call failed: {response.text}")
        return response.json()


class GitlabPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a GitlabPlugin."""

        full_name = urllib.parse.quote(f"{plugin_spec.owner}/{plugin_spec.repo}", safe="")
        repo_info = self._api_call(f"projects/{full_name}")
        default_branch = plugin_spec.branch or repo_info["default_branch"]
        api_callback = self._api_call(f"projects/{full_name}/repository/branches/{default_branch}")
        latest_commit = api_callback["commit"]
        sha = latest_commit["id"]

        self.name = plugin_spec.name
        self.owner = plugin_spec.owner
        self.version = latest_commit["committed_date"].split("T")[0]
        self.source = UrlSource(f"https://gitlab.com/api/v4/projects/{full_name}/repository/archive.tar.gz?sha={sha}")
        self.description = repo_info.get("description") or self.description
        self.homepage = repo_info["web_url"]
        self.license = plugin_spec.license or License.from_spdx_id(repo_info.get("license", {}).get("key"))
        self.source_line = plugin_spec.line
        self.updated = datetime.strptime(latest_commit["created_at"], '%Y-%m-%dT%H:%M:%S.%f%z').date()

    def _api_call(self, path: str) -> dict:
        """Call the Gitlab API."""
        url = f"https://gitlab.com/api/v4/{path}"
        response = requests.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"Gitlab API call failed: {response.text}")
        return response.json()


def _get_sourcehut_token():
    token = os.environ.get("SOURCEHUT_TOKEN")
    if token is None:
        logger.warning("SOURCEHUT_TOKEN environment variable not set")
    return token


class SourceHutPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a SourceHutPlugin."""

        repo_info = self._api_call(f"~{plugin_spec.owner}/repos/{plugin_spec.repo}")
        if plugin_spec.branch is None:
            commits = self._api_call(f"~{plugin_spec.owner}/repos/{plugin_spec.repo}/log")
        else:
            commits = self._api_call(f"~{plugin_spec.owner}/repos/{plugin_spec.repo}/log/{plugin_spec.branch}")
        latest_commit = commits["results"][0]
        sha = latest_commit["id"]

        self.name = plugin_spec.name
        self.owner = plugin_spec.owner
        self.version = latest_commit["timestamp"].split("T")[0]
        self.description = repo_info.get("description") or self.description
        self.homepage = f"https://git.sr.ht/~{plugin_spec.owner}/{plugin_spec.repo}"
        self.source = GitSource(self.homepage, sha)
        self.license = plugin_spec.license or License.UNKNOWN  # cannot be determined via API
        self.source_line = plugin_spec.line

    def _api_call(self, path: str, token: str | None = _get_sourcehut_token()):
        """Call the SourceHut API."""

        url = f"https://git.sr.ht/api/{path}"
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"token {token}"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"SourceHut API call failed: {response.json()}")
        return response.json()


def plugin_from_spec(plugin_spec: PluginSpec) -> VimPlugin:
    """Initialize a VimPlugin."""

    if plugin_spec.repository_host == RepositoryHost.GITHUB:
        return GitHubPlugin(plugin_spec)
    elif plugin_spec.repository_host == RepositoryHost.GITLAB:
        return GitlabPlugin(plugin_spec)
    elif plugin_spec.repository_host == RepositoryHost.SOURCEHUT:
        return SourceHutPlugin(plugin_spec)
    else:
        raise NotImplementedError(f"Unsupported source: {plugin_spec.repository_host}")
