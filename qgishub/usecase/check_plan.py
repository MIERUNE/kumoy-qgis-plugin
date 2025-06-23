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
