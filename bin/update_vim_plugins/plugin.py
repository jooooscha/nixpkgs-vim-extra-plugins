import logging
import os
import urllib
import json

import requests
from update_vim_plugins.nix import License, Source, UrlSource, GitSource
from update_vim_plugins.spec import PluginSpec, RepositoryHost

logger = logging.getLogger(__name__)


class VimPlugin:
    """Abstract base class for vim plugins."""

    name: str
    version: str
    source: Source
    description: str = "No description"
    homepage: str
    license: License = License.UNFREE

    def get_nix_expression(self):
        """Return the nix expression for this plugin."""
        meta = f'with lib; {{ description = "{self.description}"; homepage = "{self.homepage}"; license = with licenses; [ {self.license.value} ]; }}'
        return f'{self.name} = buildVimPluginFrom2Nix {{ pname = "{self.name}"; version = "{self.version}"; src = {self.source.get_nix_expression()}; meta = {meta}; }};'


def _get_github_token():
    token = os.environ.get("GITHUB_TOKEN")
    if token is None:
        logger.warning("GITHUB_TOKEN environment variable not set")
    return token


class GitHubPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a GitHubPlugin."""
        self.name = plugin_spec.name

        full_name = f"{plugin_spec.owner}/{plugin_spec.repo}"
        repo_info = self._api_call(f"repos/{full_name}")
        self.description = repo_info.get("description") or self.description
        self.homepage = repo_info["html_url"]
        self.license = License.from_spdx_id(repo_info.get("license", {}).get("spdx_id"))

        default_branch = plugin_spec.branch or repo_info["default_branch"]
        latest_commit = self._api_call(f"repos/{full_name}/commits/{default_branch}")
        self.version = latest_commit["commit"]["committer"]["date"].split("T")[0]

        sha = latest_commit["sha"]
        self.source = UrlSource(f"https://github.com/{full_name}/archive/{sha}.tar.gz")

    def _api_call(self, path: str, token: str | None = _get_github_token()):
        """Call the GitHub API."""
        url = f"https://api.github.com/{path}"
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"token {token}"
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            raise RuntimeError(f"GitHub API call failed: {response.status_code}")
        return response.json()


class GitlabPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a GitlabPlugin."""
        self.name = plugin_spec.name

        full_name = urllib.parse.quote(
            f"{plugin_spec.owner}/{plugin_spec.repo}", safe=""
        )
        repo_info = self._api_call(f"projects/{full_name}")
        self.description = repo_info.get("description") or self.description
        self.homepage = repo_info["web_url"]
        self.license = License.from_spdx_id(repo_info.get("license", {}).get("key"))

        default_branch = plugin_spec.branch or repo_info["default_branch"]
        latest_commit = self._api_call(
            f"projects/{full_name}/repository/branches/{default_branch}"
        )
        sha = latest_commit["commit"]["id"]
        self.version = latest_commit["commit"]["committed_date"].split("T")[0]
        self.source = UrlSource(
            f"https://gitlab.com/api/v4/projects/{full_name}/repository/archive.tar.gz?sha={sha}"
        )

    def _api_call(self, path: str) -> dict:
        """Call the Gitlab API."""
        url = f"https://gitlab.com/api/v4/{path}"
        response = requests.get(url)
        if response.status_code != 200:
            raise RuntimeError(f"Gitlab API call failed: {response.status_code}")
        return response.json()


def _get_sourcehut_token():
    token = os.environ.get("SOURCEHUT_TOKEN")
    if token is None:
        logger.warning("SOURCEHUT_TOKEN environment variable not set")
    return token


class SourceHutPlugin(VimPlugin):
    def __init__(self, plugin_spec: PluginSpec) -> None:
        """Initialize a SourceHutPlugin."""
        self.name = plugin_spec.name

        repo_info = self._api_call(f"~{plugin_spec.owner}/repos/{plugin_spec.repo}")
        print(json.dumps(repo_info, indent=2))
        self.description = repo_info.get("description") or self.description
        self.homepage = f"https://git.sr.ht/~{plugin_spec.owner}/{plugin_spec.repo}"
        self.license = License.UNFREE  # cannot be determined via API

        if plugin_spec.branch is None:
            commits = self._api_call(
                f"~{plugin_spec.owner}/repos/{plugin_spec.repo}/log"
            )
        else:
            commits = self._api_call(
                f"~{plugin_spec.owner}/repos/{plugin_spec.repo}/log/{plugin_spec.branch}"
            )
        latest_commit = commits["results"][0]
        print(json.dumps(latest_commit, indent=2))
        self.version = latest_commit["timestamp"].split("T")[0]
        sha = latest_commit["id"]

        self.source = GitSource(self.homepage, sha)

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


def plugin_from_spec(plugin_spec: PluginSpec) -> None:
    """Initialize a VimPlugin."""
    if plugin_spec.repository_host == RepositoryHost.GITHUB:
        return GitHubPlugin(plugin_spec)
    elif plugin_spec.repository_host == RepositoryHost.GITLAB:
        return GitlabPlugin(plugin_spec)
    elif plugin_spec.repository_host == RepositoryHost.SOURCEHUT:
        return SourceHutPlugin(plugin_spec)
    else:
        raise NotImplementedError(f"Unsupported source: {plugin_spec.repository_host}")
