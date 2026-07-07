"""Permit portal workflow automation."""

from scraper_framework.smart_crawler.permit_workflows.generic import GenericPermitWorkflow
from scraper_framework.smart_crawler.permit_workflows.models import PermitWorkflowOptions, PermitWorkflowResult

__all__ = ["GenericPermitWorkflow", "PermitWorkflowOptions", "PermitWorkflowResult"]
