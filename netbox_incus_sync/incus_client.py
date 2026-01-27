import requests_unixsocket
import logging
import urllib.parse
from django.conf import settings

logger = logging.getLogger(__name__)

class IncusClient:
    def __init__(self, socket_url=None):
        if not socket_url:
            conf = settings.PLUGINS_CONFIG.get('netbox_incus_sync', {})
            socket_url = conf.get('socket_path', 'http+unix://%2Fvar%2Flib%2Fincus%2Funix.socket')
        
        self.base_url = socket_url
        self.session = requests_unixsocket.Session()

    def get_instances(self):
        """
        Récupère la liste complète des instances avec leurs détails de configuration.
        """
        endpoint = f"{self.base_url}/1.0/instances?recursion=1"
        try:
            response = self.session.get(endpoint)
            response.raise_for_status()
            
            data = response.json()
            
            # Validation de la structure de réponse Incus standard
            # Structure attendue : { "type": "sync", "status": "Success", "metadata": [... ] }
            if data.get('type')!= 'sync':
                logger.error(f"Type de réponse Incus inattendu : {data.get('type')}")
                return
            
            return data.get('metadata',)
            
        except Exception as e:
            logger.error(f"Erreur de communication avec Incus sur {self.base_url}: {str(e)}")
            raise e