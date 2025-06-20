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
    # Get project details to find organization ID
    project = api.project.get_project(project_id)
    if project is None:
        return None

    # Get organization details to find plan information
    organization = api.organization.get_organization(project.organizationId)
    if organization is None:
        return None

    # Get plan limits for the plan
    return api.plan.get_plan_limits(organization.plan)


def check_vector_count_limit(current_vector_count: int, plan_max_vectors: int) -> bool:
    """Check if adding one more vector would exceed plan limit"""
    # Check if adding one more vector would exceed limit
    if current_vector_count >= plan_max_vectors:
        return False
    return True


def check_feature_count_limit(feature_count: int, plan_max_features: int) -> bool:
    """Check if layer feature count would exceed plan limit"""
    if feature_count > plan_max_features:
        return False
    return True


def check_attribute_count_limit(
    layer_field_count: int, plan_max_attributes: int
) -> bool:
    """Check if layer attribute count would exceed plan limit"""
    if layer_field_count > plan_max_attributes:
        return False
    return True
