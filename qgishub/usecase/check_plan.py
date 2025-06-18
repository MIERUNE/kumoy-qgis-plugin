from typing import Optional

from qgis.PyQt.QtCore import QCoreApplication

from .. import api


def tr(message: str) -> str:
    """Translate a message using Qt's translation system"""
    return QCoreApplication.translate("CheckPlan", message)


def get_plan_limits(project_id: str) -> Optional[api.plan.PlanLimits]:
    """
    Get plan limits for a project

    Args:
        project_id: Project ID

    Returns:
        PlanLimits object or None if not available
    """
    try:
        # Get project details to find organization ID
        project = api.project.get_project(project_id)
        if not project or not project.organizationId:
            raise Exception("Project not found or organization ID missing")

        # Get organization details to find plan information
        organization = api.organization.get_organization(project.organizationId)
        if not organization or not organization.plan:
            raise Exception("Organization not found or plan information missing")

        # Get plan limits for the plan
        return api.plan.get_plan_limits(organization.plan)

    except Exception:
        return None


def check_vector_count_limit(current_vector_count: int, plan_max_vectors: int) -> bool:
    """Check if adding one more vector would exceed plan limit"""
    try:
        # Check if adding one more vector would exceed limit
        if current_vector_count >= plan_max_vectors:
            return False
        return True
    except Exception as e:
        # Log error but don't block upload for other errors
        raise Exception(tr(f"Error: {str(e)}\n")) from e


def check_feature_count_limit(feature_count: int, plan_max_features: int) -> bool:
    """Check if layer feature count would exceed plan limit"""
    try:
        if feature_count > plan_max_features:
            return False
        return True
    except Exception as e:
        raise Exception(tr(f"Error: {str(e)}\n")) from e


def check_attribute_count_limit(
    layer_field_count: int, plan_max_attributes: int
) -> bool:
    """Check if layer attribute count would exceed plan limit"""
    try:
        if layer_field_count > plan_max_attributes:
            return False
        return True
    except Exception as e:
        raise Exception(tr(f"Error: {str(e)}\n")) from e
