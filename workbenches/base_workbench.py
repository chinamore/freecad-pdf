"""
Abstract Base Class for FreeCAD-style Workbenches
"""
from abc import ABC, abstractmethod

class BaseWorkbench(ABC):
    def __init__(self, main_window):
        self.main_window = main_window

    @abstractmethod
    def get_central_widget(self):
        """Returns the main workspace widget for this workbench."""
        pass

    @abstractmethod
    def setup_toolbar(self, toolbar):
        """Populates the top action toolbar for this workbench."""
        pass

    @abstractmethod
    def update_dock_views(self, tree_widget, property_table):
        """Updates the left Model Tree and Property Inspector."""
        pass

    @abstractmethod
    def export_data(self):
        """Export workbench specific data."""
        pass