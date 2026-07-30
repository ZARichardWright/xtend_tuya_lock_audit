DOMAIN = "tuya_lock"
VERSION = "0.4.0"
CONF_ENDPOINT = "endpoint"
CONF_ACCESS_ID = "access_id"
CONF_ACCESS_SECRET = "access_secret"
CONF_DEVICE_ID = "device_id"
DEFAULT_ENDPOINT = "https://openapi.tuyaeu.com"
SERVICE_CREATE_TEMPORARY_PIN = "create_temporary_pin"
SERVICE_DELETE_TEMPORARY_PIN = "delete_temporary_pin"

# Tuya smart locks are normally category ``ms``. Some products expose a more
# specific lock category, so retain the known subtypes as well.
LOCK_CATEGORIES = {"ms", "mk", "jtmsbh", "jtmspro", "videolock"}
