import requests
import requests_unixsocket
import logging
import os

logger = logging.getLogger(__name__)


class IncusClient:
    """
    Client pour communiquer avec l'API Incus.
    
    Supporte deux modes de connexion :
    - Socket Unix (local) : http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket
    - HTTPS (distant) : https://incus.example.com:8443 avec certificats TLS
    
    Sécurité :
    - Les certificats sont lus directement depuis les fichiers système
    - Aucun secret n'est stocké en mémoire plus longtemps que nécessaire
    - Les fichiers temporaires ne sont jamais utilisés
    """

    def __init__(self, host=None, socket_url=None, https_url=None,
                 client_cert_path=None, client_key_path=None, 
                 ca_cert_path=None, verify_ssl=True):
        """
        Initialise le client Incus.

        Args:
            host: Instance IncusHost (prioritaire si fourni)
            socket_url: URL du socket Unix
            https_url: URL HTTPS du serveur
            client_cert_path: Chemin vers le certificat client (.crt)
            client_key_path: Chemin vers la clé privée (.key)
            ca_cert_path: Chemin vers le certificat CA (optionnel)
            verify_ssl: Vérifier le certificat SSL du serveur
        """
        self.session = None
        self.base_url = None

        # Si un objet IncusHost est passé, extraire la config
        if host is not None:
            from .models import ConnectionTypeChoices
            if host.connection_type == ConnectionTypeChoices.HTTPS:
                https_url = host.https_url
                client_cert_path = host.client_cert_path
                client_key_path = host.client_key_path
                ca_cert_path = host.ca_cert_path
                verify_ssl = host.verify_ssl
            else:
                socket_url = host.socket_path

        # Configuration selon le type de connexion
        if https_url:
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
            # Fallback sur socket par défaut
            self._setup_unix_socket('http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket')

    def _setup_unix_socket(self, socket_url):
        """Configure la connexion via socket Unix."""
        self.base_url = socket_url
        self.session = requests_unixsocket.Session()
        logger.debug(f"Client Incus configuré en mode Unix socket: {socket_url}")

    def _setup_https(self, https_url, client_cert_path, client_key_path, 
                     ca_cert_path, verify_ssl):
        """
        Configure la connexion via HTTPS avec certificats TLS.
        
        Les certificats sont passés directement par leurs chemins de fichiers
        à la bibliothèque requests, qui les lit de manière sécurisée.
        """
        self.base_url = https_url.rstrip('/')
        self.session = requests.Session()

        # Vérification des fichiers de certificats
        if client_cert_path and client_key_path:
            # Vérifier que les fichiers existent
            for path, name in [(client_cert_path, 'certificat'), 
                               (client_key_path, 'clé privée')]:
                if not os.path.isfile(path):
                    raise FileNotFoundError(f"Fichier {name} introuvable: {path}")
                if not os.access(path, os.R_OK):
                    raise PermissionError(f"Fichier {name} non lisible: {path}")
            
            # requests accepte un tuple (cert, key) avec les chemins de fichiers
            # C'est la méthode recommandée et sécurisée
            self.session.cert = (client_cert_path, client_key_path)
            logger.debug(f"Certificat client configuré: {client_cert_path}")

        # Configuration de la vérification SSL
        if ca_cert_path and os.path.isfile(ca_cert_path):
            # Utiliser un CA spécifique pour valider le serveur
            self.session.verify = ca_cert_path
            logger.debug(f"CA personnalisé configuré: {ca_cert_path}")
        else:
            self.session.verify = verify_ssl
            if not verify_ssl:
                logger.warning("Vérification SSL désactivée - non recommandé en production!")
                # Désactiver les avertissements urllib3 pour les certificats non vérifiés
                import urllib3
                urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        logger.debug(f"Client Incus configuré en mode HTTPS: {https_url}")

    def _request(self, method, endpoint, **kwargs):
        """Effectue une requête HTTP vers l'API Incus."""
        url = f"{self.base_url}{endpoint}"
        
        try:
            response = self.session.request(method, url, timeout=30, **kwargs)
            response.raise_for_status()
            return response.json()
            
        except requests.exceptions.SSLError as e:
            logger.error(f"Erreur SSL lors de la connexion à {url}: {e}")
            raise ConnectionError(
                f"Erreur SSL: {e}. "
                "Vérifiez les certificats ou le CA, ou désactivez la vérification SSL."
            )
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Impossible de se connecter à {url}: {e}")
            raise ConnectionError(f"Impossible de se connecter à Incus: {e}")
        except requests.exceptions.Timeout as e:
            logger.error(f"Timeout lors de la connexion à {url}: {e}")
            raise ConnectionError(f"Timeout de connexion à Incus: {e}")
        except Exception as e:
            logger.error(f"Erreur lors de la requête à {url}: {e}")
            raise

    def get_instances(self, recursion=1):
        """
        Récupère la liste des instances avec leurs détails.

        Args:
            recursion: Niveau de détail (0=noms, 1=config, 2=état complet)

        Returns:
            Liste des instances
        """
        data = self._request('GET', f'/1.0/instances?recursion={recursion}')

        if data.get('type') != 'sync':
            logger.error(f"Type de réponse Incus inattendu: {data.get('type')}")
            return []

        return data.get('metadata', [])

    def get_instance(self, name):
        """Récupère les détails d'une instance spécifique."""
        data = self._request('GET', f'/1.0/instances/{name}')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_instance_state(self, name):
        """Récupère l'état d'une instance (CPU, mémoire, réseau, etc.)."""
        data = self._request('GET', f'/1.0/instances/{name}/state')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_server_info(self):
        """Récupère les informations du serveur Incus."""
        data = self._request('GET', '/1.0')
        if data.get('type') == 'sync':
            return data.get('metadata')
        return None

    def get_networks(self):
        """Récupère la liste des réseaux."""
        data = self._request('GET', '/1.0/networks?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []

    def get_storage_pools(self):
        """Récupère la liste des pools de stockage."""
        data = self._request('GET', '/1.0/storage-pools?recursion=1')
        if data.get('type') == 'sync':
            return data.get('metadata', [])
        return []

    def get_storage_volume(self, pool, volume_type, volume_name):
        """
        Récupère les informations d'un volume de stockage.
        
        Args:
            pool: Nom du pool de stockage (ex: 'default')
            volume_type: Type de volume ('container', 'virtual-machine', 'custom', 'image')
            volume_name: Nom du volume
        
        Returns:
            dict: Informations du volume ou None
        """
        try:
            data = self._request(
                'GET', 
                f'/1.0/storage-pools/{pool}/volumes/{volume_type}/{volume_name}'
            )
            if data.get('type') == 'sync':
                return data.get('metadata')
        except Exception as e:
            logger.debug(f"Volume {volume_type}/{volume_name} non trouvé dans {pool}: {e}")
        return None

    def test_connection(self):
        """
        Teste la connexion au serveur Incus.

        Returns:
            tuple: (success: bool, message: str)
        """
        try:
            info = self.get_server_info()
            if info:
                env = info.get('environment', {})
                server_name = env.get('server_name', 'Inconnu')
                version = env.get('server_version', 'Inconnue')
                return True, f"Connecté à {server_name} (version {version})"
            return False, "Réponse invalide du serveur"
        except FileNotFoundError as e:
            return False, f"Fichier certificat manquant: {e}"
        except PermissionError as e:
            return False, f"Permission refusée: {e}"
        except ConnectionError as e:
            return False, str(e)
        except Exception as e:
            return False, f"Erreur inattendue: {e}"