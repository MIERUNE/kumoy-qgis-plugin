FORMS = ui/dialog_config.ui

SOURCES = __init__.py \
          qgishub_plugin.py \
          browser/root.py \
          browser/styledmap.py \
          browser/vector.py \
          browser/utils.py \
          ui/dialog_config.py \
          ui/dialog_project_select.py \
          settings_manager.py \
          qgishub/auth_manager.py \
          qgishub/config.py \
          qgishub/constants.py \
          qgishub/api/auth.py \
          qgishub/api/client.py \
          qgishub/api/organization.py \
          qgishub/api/project.py \
          qgishub/api/project_styledmap.py \
          qgishub/api/project_vector.py \
          qgishub/api/qgis_vector.py \
          qgishub/provider/dataprovider.py \
          qgishub/provider/dataprovider_metadata.py \
          qgishub/provider/feature_iterator.py \
          qgishub/provider/feature_source.py \
          processing/provider.py \
          processing/algorithms/upload_vector_algorithm.py

TRANSLATIONS = i18n/qgis_hub_ja.ts