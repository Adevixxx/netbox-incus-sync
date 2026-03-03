"""
Base Incus API client — connection setup, HTTP transport, URL management.

This module contains the core transport layer shared by all API modules:
- Unix socket and HTTPS connection setup
- TLS certificate handling
- HTTP request execution with error handling
- Multi-URL failover and caching logic
"""

import requests
import requests_unixsocket
import logging
import os

logger = logging.getLogger(__name__)


class IncusClientBase:
    """
    Base transport layer for the Incus API client.

    Supports two connection modes:
    - Unix Socket (local): http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket
    - HTTPS (remote): https://incus.example.com:8443 with TLS certificates

    Security:
    - Certificates are read directly from system files
    - No secrets are stored in memory longer than necessary
    - Temporary files are never used
    """

    def __init__(
        self,
        host=None,
        socket_url=None,
        https_url=None,
        client_cert_path=None,
        client_key_path=None,
        ca_cert_path=None,
        verify_ssl=True,
    ):
        """
        Initializes the Incus client.

        Args:
            host: IncusHost instance (priority if provided)
            socket_url: Unix socket URL
            https_url: Server HTTPS URL
            client_cert_path: Path to client certificate (.crt)
            client_key_path: Path to private key (.key)
            ca_cert_path: Path to CA certificate (optional)
            verify_ssl: Verify server SSL certificate
        """
        self.session = None
        self.base_url = None
        self._host = host
        self._client_cert_path = client_cert_path
        self._client_key_path = client_key_path
        self._ca_cert_path = ca_cert_path
        self._verify_ssl = verify_ssl

        # If an IncusHost object is passed, extract config
        if host is not None:
            from ..models import ConnectionTypeChoices

            if host.connection_type == ConnectionTypeChoices.HTTPS:
                self._client_cert_path = host.client_cert_path
                self._client_key_path = host.client_key_path
                self._ca_cert_path = host.ca_cert_path
                self._verify_ssl = host.verify_ssl

                # Use multi-URL logic
                working_url = self._get_working_url(host)
                if working_url:
                    self._setup_https(
                        working_url,
                        self._client_cert_path,
                        self._client_key_path,
                        self._ca_cert_path,
                        self._verify_ssl,
                    )
                else:
                    raise ConnectionError("No working URL found among configured URLs")
            else:
                socket_url = host.socket_path
                self._setup_unix_socket(socket_url)
        elif https_url:
            self._setup_https(
                https_url, client_cert_path, client_key_path, ca_cert_path, verify_ssl
            )
        elif socket_url:
            self._setup_unix_socket(socket_url)
        else:
            # Fallback to default socket
            self._setup_unix_socket("http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket")

    # ========== Query Helpers ==========

    def _build_project_query(self, base_params="", project=None):
        """
        Builds query string, appending ?project= when needed.

        The Incus API uses ``?project=<name>`` to scope requests to
        a specific project.  The ``default`` project is implicit and
        does not need the parameter.

        Args:
            base_params: Existing query params (e.g. 'recursion=2')
            project: Incus project name (None or 'default' → skip)

        Returns:
            str: Query string starting with '?' or empty string
        """
        parts = []
        if base_params:
            parts.append(base_params)
        if project and project != "default":
            parts.append(f"project={project}")
        return "?" + "&".join(parts) if parts else ""

    # ========== Connection Setup ==========

    def _setup_unix_socket(self, socket_url):
        """Configures connection via Unix socket."""
        self.base_url = socket_url
        self.session = requests_unixsocket.Session()
        logger.debug(f"Incus client configured in Unix socket mode: {socket_url}")

    def _setup_https(
        self, https_url, client_cert_path, client_key_path, ca_cert_path, verify_ssl
    ):
        """
        Configures connection via HTTPS with TLS certificates.

        Certificates are passed directly by their file paths
        to the requests library, which reads them securely.
        """
        self.base_url = https_url.rstrip("/")
        self.session = requests.Session()

        # Certificate files verification
        if client_cert_path and client_key_path:
            # Check that files exist
            for path, name in [
                (client_cert_path, "certificate"),
                (client_key_path, "private key"),
            ]:
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"File {name} not found: {path}")
                if not os.access(path, os.R_OK):
                    raise PermissionError(f"File {name} not readable: {path}")

            # requests accepts a tuple (cert, key) with file paths
            # This is the recommended and secure method
            self.session.cert = (client_cert_path, client_key_path)
            logger.debug(f"Client certificate configured: {client_cert_path}")

        # SSL verification configuration
        if ca_cert_path and os.path.isfile(ca_cert_path):
            # Use a specific CA to validate the server
            self.session.verify = ca_cert_path
            logger.debug(f"Custom CA configured: {ca_cert_path}")
        else:
            self.session.verify = verify_ssl
            if not verify_ssl:
                logger.warning(
                    "SSL verification disabled - not recommended in production!"
                )
                # Disable urllib3 warnings for unverified certificates
                import urllib3

                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.debug(f"Incus client configured in HTTPS mode: {https_url}")

    # ========== HTTP Transport ==========

    def _request(self, method, endpoint, **kwargs):
        """Performs an HTTP request to the Incus API."""
        url = f"{self.base_url}{endpoint}"

        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()

        except requests.exceptions.SSLError as e:
            logger.error(f"SSL error connecting to {url}: {e}")
            # Invalidate cache on SSL errors
            if self._host:
                self._host.clear_url_cache()
            raise ConnectionError(
                f"SSL Error: {e}. "
                "Check certificates or CA, or disable SSL verification."
            )
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Unable to connect to {url}: {e}")
            # Invalidate cache on connection errors
            if self._host:
                self._host.clear_url_cache()
            raise ConnectionError(f"Unable to connect to Incus: {e}")
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout connecting to {url}: {e}")
            raise ConnectionError(f"Connection timeout to Incus: {e}")
        except Exception as e:
            logger.error(f"Error requesting {url}: {e}")
            raise

    # ========== Multi-URL Management ==========

    def _get_working_url(self, host):
        """
        Gets a working URL from the host configuration.

        Strategy:
        1. If cache is valid, use cached URL directly
        2. Otherwise, test URLs in order (cached URL first if exists)
        3. Update cache when a working URL is found

        Args:
            host: IncusHost instance

        Returns:
            str: Working URL or None
        """
        urls = host.get_https_urls()

        if not urls:
            logger.error("No HTTPS URLs configured for host")
            return None

        # Check if cache is valid - using is_url_cache_valid() method
        if host.is_url_cache_valid():
            logger.debug(f"Using cached URL: {host.last_working_url}")
            return host.last_working_url

        # Reorder URLs: put cached URL first if it exists
        if host.last_working_url and host.last_working_url in urls:
            urls = [host.last_working_url] + [
                u for u in urls if u != host.last_working_url
            ]
            logger.debug(f"Testing {len(urls)} URLs, cached URL first")
        else:
            logger.debug(f"Testing {len(urls)} URLs")

        # Test each URL
        for url in urls:
            if self._test_url_connection(url, host):
                logger.info(f"Working URL found: {url}")
                host.update_working_url(url)
                return url
            else:
                logger.debug(f"URL failed: {url}")

        logger.error(f"No working URL found among {len(urls)} URLs")
        return None

    def _test_url_connection(self, url, host):
        """
        Tests if a specific URL is reachable.

        Args:
            url: URL to test
            host: IncusHost instance (for certificate config)

        Returns:
            bool: True if connection successful
        """
        test_session = None
        try:
            test_session = requests.Session()

            # Configure certificates
            if self._client_cert_path and self._client_key_path:
                if os.path.isfile(self._client_cert_path) and os.path.isfile(
                    self._client_key_path
                ):
                    test_session.cert = (self._client_cert_path, self._client_key_path)

            # Configure SSL verification
            if self._ca_cert_path and os.path.isfile(self._ca_cert_path):
                test_session.verify = self._ca_cert_path
            else:
                test_session.verify = self._verify_ssl
                if not self._verify_ssl:
                    import urllib3

                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

            # Quick connection test with short timeout
            test_url = f"{url.rstrip('/')}/1.0"
            response = test_session.get(test_url, timeout=5)
            response.raise_for_status()

            data = response.json()
            if data.get("type") == "sync":
                return True

            return False

        except requests.exceptions.SSLError as e:
            logger.debug(f"SSL error testing {url}: {e}")
            return False
        except requests.exceptions.ConnectionError as e:
            logger.debug(f"Connection error testing {url}: {e}")
            return False
        except requests.exceptions.Timeout as e:
            logger.debug(f"Timeout testing {url}: {e}")
            return False
        except Exception as e:
            logger.debug(f"Error testing {url}: {e}")
            return False
        finally:
            if test_session:
                test_session.close()
