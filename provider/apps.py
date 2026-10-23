from django.apps import AppConfig


class ProviderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'provider'

    def ready(self):
        import provider.signals  # ← ADD THIS LINE