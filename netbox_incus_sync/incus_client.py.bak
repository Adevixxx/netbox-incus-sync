import requests
import requests_unixsocket
import logging
import os

logger = logging.getLogger(__name__)


class IncusClient:
    """
    Client to communicate with the Incus API.
    
    Supports two connection modes:
    - Unix Socket (local): http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket
    - HTTPS (remote): https://incus.example.com:8443 with TLS certificates
    
    Security:
    - Certificates are read directly from system files
    - No secrets are stored in memory longer than necessary
    - Temporary files are never used
    """

    def __init__(self, host=None, socket_url=None, https_url=None,
                 client_cert_path=None, client_key_path=None, 
                 ca_cert_path=None, verify_ssl=True):
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
            from .models import ConnectionTypeChoices
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
                        self._verify_ssl
                    )
                else:
                    raise ConnectionError("No working URL found among configured URLs")
            else:
                socket_url = host.socket_path
                self._setup_unix_socket(socket_url)
        elif https_url:
            self._setup_https(
                https_url, 
                client_cert_path, 
                client_key_path,
                ca_cert_path,
                verify_ssl
            )
        elif socket_url:
            self._setup_unix_socket(socket_url)
        else:
            # Fallback to default socket
            self._setup_unix_socket('http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket')

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
            urls = [host.last_working_url] + [u for u in urls if u != host.last_working_url]
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
                if os.path.isfile(self._client_cert_path) and os.path.isfile(self._client_key_path):
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
            if data.get('type') == 'sync':
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

    def _setup_unix_socket(self, socket_url):
        """Configures connection via Unix socket."""
        self.base_url = socket_url
        self.session = requests_unixsocket.Session()
        logger.debug(f"Incus client configured in Unix socket mode: {socket_url}")

    def _setup_https(self, https_url, client_cert_path, client_key_path, 
                     ca_cert_path, verify_ssl):
        """
        Configures connection via HTTPS with TLS certificates.
        
        Certificates are passed directly by their file paths
        to the requests library, which reads them securely.
        """
        self.base_url = https_url.rstrip('/')
        self.session = requests.Session()

        # Certificate files verification
        if client_cert_path and client_key_path:
            # Check that files exist
            for path, name in [(client_cert_path, 'certificate'), 
                               (client_key_path, 'private key')]:
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
                logger.warning("SSL verification disabled - not recommended in production!")
                # Disable urllib3 warnings for unverified certificates
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.debug(f"Incus client configured in HTTPS mode: {https_url}")

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

    def get_instances(self, recursion=1):
        """
        Retrieves the list of instances with their details.

        Args:
            recursion: Detail level (0=names, 1=config, 2=full state)
                       Use recursion=2 to get expanded_config and state

        Returns:
            List of instances
        """
        data = self._request('GET', f'/1.0/instances?recursion={recursion}')

        if data.get('type') != 'sync':
            logger.error(f"Unexpected Incus response type: {data.get('type')}")
            return []

        return data.get('metadata', [])

    def get_instance(self, name):
        """Retrieves details of a specific instance."""
        data = self._request('GET', f'/1.0/instances/{name}')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_instance_state(self, name):
        """Retrieves the state of an instance (CPU, memory, network, etc.)."""
        data = self._request('GET', f'/1.0/instances/{name}/state')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_instance_logs(self, name):
        """
        Retrieves the list of log files for an instance.
        
        Args:
            name: Instance name
        
        Returns:
            list: List of log filenames
        """
        try:
            data = self._request('GET', f'/1.0/instances/{name}/logs')
            if data.get('type') == 'sync':
                # Logs are returned as URLs, extract names
                logs = data.get('metadata', [])
                return [log.split('/')[-1] for log in logs]
        except Exception as e:
            logger.debug(f"Unable to retrieve logs for {name}: {e}")
        return []

    def get_instance_log_content(self, name, log_file):
        """
        Retrieves the content of an instance log file.
        
        Args:
            name: Instance name
            log_file: Log filename (e.g., 'lxc.log')
        
        Returns:
            str: Log file content
        """
        try:
            url = f"{self.base_url}/1.0/instances/{name}/logs/{log_file}"
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except Exception as e:
            logger.debug(f"Unable to read log {log_file} for {name}: {e}")
        return None

    # ========== Console / Screenshot API ==========

    def get_instance_screenshot(self, name):
        """
        Captures a VGA console screenshot of a virtual machine.
        
        Only works for VMs (not containers) that are running.
        Uses the GET /1.0/instances/NAME/console?type=vga endpoint
        which returns a PNG image.
        
        Requires Incus >= 6.7 (api extension: instance_console_screenshot).
        
        Args:
            name: Instance name
        
        Returns:
            bytes: PNG image data, or None if unavailable
        """
        url = f"{self.base_url}/1.0/instances/{name}/console?type=vga"
        
        try:
            response = self.session.get(url, timeout=15)
            response.raise_for_status()
            
            # The endpoint returns raw PNG data
            content_type = response.headers.get('Content-Type', '')
            if 'image' in content_type or response.content[:4] == b'\x89PNG':
                return response.content
            
            # If we got JSON back, it's probably an error
            logger.warning(f"Screenshot for {name}: unexpected content type {content_type}")
            return None
            
        except requests.exceptions.HTTPError as e:
            if e.response is not None and e.response.status_code == 400:
                logger.debug(f"Screenshot not available for {name} (possibly a container or stopped VM)")
            else:
                logger.warning(f"HTTP error getting screenshot for {name}: {e}")
            return None
        except Exception as e:
            logger.debug(f"Unable to capture screenshot for {name}: {e}")
            return None

    def get_server_info(self):
        """Retrieves Incus server information."""
        data = self._request('GET', '/1.0')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_networks(self):
        """Retrieves the list of networks."""
        data = self._request('GET', '/1.0/networks?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []

    def get_profiles(self, recursion=1):
        """Retrieves the list of Incus profiles with their configuration."""
        try:
            data = self._request('GET', f'/1.0/profiles?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.error(f"Unable to retrieve profiles: {e}")
        return []

    def get_profile(self, name):
        """Retrieves details of a specific profile."""
        try:
            data = self._request('GET', f'/1.0/profiles/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Profile {name} not found: {e}")
        return None

    def get_storage_pools(self):
        """Retrieves the list of storage pools."""
        data = self._request('GET', '/1.0/storage-pools?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []

    def get_storage_pool_info(self, pool_name):
        """
        Retrieves information about a specific storage pool.
        
        Args:
            pool_name: Storage pool name
        
        Returns:
            dict: Pool information including driver type, or None
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool_name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Pool {pool_name} not found: {e}")
        return None

    def get_storage_pool_resources(self, pool_name):
        """
        Retrieves resource usage information for a storage pool.
        
        Args:
            pool_name: Storage pool name
        
        Returns:
            dict: Pool resources (space used, total, inodes, etc.)
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool_name}/resources')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Unable to get resources for pool {pool_name}: {e}")
        return None

    def get_storage_volume(self, pool, volume_type, volume_name):
        """
        Retrieves information about a storage volume.
        
        Args:
            pool: Storage pool name (e.g., 'default')
            volume_type: Volume type ('container', 'virtual-machine', 'custom', 'image')
            volume_name: Volume name
        
        Returns:
            dict: Volume information or None
        """
        try:
            data = self._request(
                'GET', 
                f'/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}'
            )
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Volume {volume_type}/{volume_name} not found in {pool}: {e}")
        return None

    def get_storage_volume_state(self, pool, volume_type, volume_name):
        """
        Retrieves the state/usage information for a storage volume.
        
        Args:
            pool: Storage pool name
            volume_type: Volume type ('container', 'virtual-machine', 'custom')
            volume_name: Volume name
        
        Returns:
            dict: Volume state with usage info
        """
        try:
            data = self._request(
                'GET',
                f'/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}/state'
            )
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Unable to get state for volume {volume_type}/{volume_name} in {pool}: {e}")
        return None

    def get_storage_volumes(self, pool, recursion=1):
        """
        Retrieves all volumes in a storage pool.
        
        Args:
            pool: Storage pool name
            recursion: Detail level (0=URLs, 1=full details)
        
        Returns:
            list: List of volumes
        """
        try:
            data = self._request('GET', f'/1.0/storage-pools/{pool}/volumes?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to get volumes for pool {pool}: {e}")
        return []

    def get_operations(self, recursion=1):
        """
        Retrieves the list of operations (action history).
        
        Args:
            recursion: Detail level (0=IDs, 1=full details)
        
        Returns:
            list: List of operations
        """
        try:
            data = self._request('GET', f'/1.0/operations?recursion={recursion}')
            if data.get('type') == 'sync':
                metadata = data.get('metadata', {})
                
                all_operations = []
                
                if isinstance(metadata, dict):
                    for status, ops in metadata.items():
                        if isinstance(ops, list):
                            all_operations.extend(ops)
                elif isinstance(metadata, list):
                    all_operations = metadata
                
                return all_operations
        except Exception as e:
            logger.debug(f"Unable to retrieve operations: {e}")
        return []

    def get_operation(self, operation_id):
        """
        Retrieves details of a specific operation.
        
        Args:
            operation_id: Operation UUID
        
        Returns:
            dict: Operation details or None
        """
        try:
            data = self._request('GET', f'/1.0/operations/{operation_id}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Operation {operation_id} not found: {e}")
        return None

    # ========== Cluster API ==========

    def get_cluster(self):
        """
        Retrieves cluster information.
        
        Returns:
            dict: Cluster information or None if no cluster
        """
        try:
            data = self._request('GET', '/1.0/cluster')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"No cluster configured: {e}")
        return None

    def get_cluster_members(self, recursion=1):
        """
        Retrieves the list of cluster members.
        
        Args:
            recursion: Detail level (0=URLs, 1=full details)
        
        Returns:
            list: List of cluster members
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to retrieve cluster members: {e}")
        return []

    def get_cluster_member(self, name):
        """
        Retrieves details of a cluster member.
        
        Args:
            name: Member name
        
        Returns:
            dict: Member details or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Member {name} not found: {e}")
        return None

    def get_cluster_member_state(self, name):
        """
        Retrieves the state of a cluster member (CPU, memory, etc.).
        
        Args:
            name: Member name
        
        Returns:
            dict: Member state or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/members/{name}/state')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Member state {name} not available: {e}")
        return None

    def get_cluster_groups(self, recursion=1):
        """
        Retrieves the list of cluster groups.
        
        Args:
            recursion: Detail level
        
        Returns:
            list: List of cluster groups
        """
        try:
            data = self._request('GET', f'/1.0/cluster/groups?recursion={recursion}')
            if data.get('type') == 'sync':
                return data.get('metadata', [])
        except Exception as e:
            logger.debug(f"Unable to retrieve cluster groups: {e}")
        return []

    def get_cluster_group(self, name):
        """
        Retrieves details of a cluster group.
        
        Args:
            name: Group name
        
        Returns:
            dict: Group details or None
        """
        try:
            data = self._request('GET', f'/1.0/cluster/groups/{name}')
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Group {name} not found: {e}")
        return None

    def test_connection(self):
        """
        Tests connection to the Incus server.

        Returns:
            tuple: (success: bool, message: str, extra_info: dict)
        """
        try:
            info = self.get_server_info()
            if info:
                env = info.get('environment', {})
                server_name = env.get('server_name', 'Unknown')
                version = env.get('server_version', 'Unknown')
                
                # Check if it is a cluster
                cluster_info = self.get_cluster()
                cluster_enabled = cluster_info.get('enabled', False) if cluster_info else False
                
                extra_info = {
                    'server_name': server_name,
                    'version': version,
                    'cluster_enabled': cluster_enabled,
                    'connected_url': self.base_url,
                }
                
                if cluster_enabled:
                    members = self.get_cluster_members()
                    extra_info['cluster_members'] = len(members)
                    return True, f"Connected to {server_name} (version {version}) - Cluster with {len(members)} nodes", extra_info
                
                return True, f"Connected to {server_name} (version {version})", extra_info
            return False, "Invalid server response", {}
        except FileNotFoundError as e:
            return False, f"Missing certificate file: {e}", {}
        except PermissionError as e:
            return False, f"Permission denied: {e}", {}
        except ConnectionError as e:
            return False, str(e), {}
        except Exception as e:
            return False, f"Unexpected error: {e}", {}

    def test_all_urls(self, host):
        """
        Tests all configured URLs and returns their status.
        
        Args:
            host: IncusHost instance
            
        Returns:
            list: List of dicts with 'url', 'success', 'message' keys
        """
        results = []
        urls = host.get_https_urls()
        
        for url in urls:
            try:
                success = self._test_url_connection(url, host)
                if success:
                    results.append({
                        'url': url,
                        'success': True,
                        'message': 'Connection successful'
                    })
                else:
                    results.append({
                        'url': url,
                        'success': False,
                        'message': 'Connection failed'
                    })
            except Exception as e:
                results.append({
                    'url': url,
                    'success': False,
                    'message': str(e)
                })
        
        return results