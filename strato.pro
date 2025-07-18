FORMS = ui/dialog_config.ui

SOURCES = __init__.py \
          plugin.py \
          browser/root.py \
          browser/styledmap.py \
          browser/vector.py \
          browser/utils.py \
          ui/dialog_config.py \
          ui/dialog_project_select.py \
          settings_manager.py \
          strato/auth_manager.py \
          strato/config.py \
          strato/constants.py \
          strato/api/auth.py \
          strato/api/client.py \
          strato/api/organization.py \
          strato/api/project.py \
          strato/api/project_styledmap.py \
          strato/api/project_vector.py \
          strato/api/qgis_vector.py \
          strato/provider/dataprovider.py \
          strato/provider/dataprovider_metadata.py \
          strato/provider/feature_iterator.py \
          strato/provider/feature_source.py \
          processing/provider.py \
          processing/feature_uploader.py \
          processing/field_name_normalizer.py \
          processing/vector_creator.py \
          processing/algs/upload_vector_algorithm.py

TRANSLATIONS = i18n/strato_ja.ts