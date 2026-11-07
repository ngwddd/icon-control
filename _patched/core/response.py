"""Helper functions for formatting MCP tool responses."""

import json
from typing import TYPE_CHECKING, Any, Optional, Union

from mcp.types import ImageContent, TextContent

from computer_mcp.core.utils import screenshot_to_image_content

if TYPE_CHECKING:
    from computer_mcp.core.state import ComputerState


def format_response(
    result: dict[str, Any],
    state: "ComputerState",
    screenshot_data: Optional[dict[str, Any]] = None
) -> list[Union[TextContent, ImageContent]]:
    """Format a tool response with optional screenshot as ImageContent.
    
    Args:
        result: Dictionary with tool action result (will be merged with state)
        state: ComputerState instance
        screenshot_data: Optional pre-captured screenshot data to use instead of capturing new one
        
    Returns:
        List containing ImageContent (if screenshot enabled) and TextContent
    """
    result_state = state.get_state(include_screenshot=screenshot_data is None)
    
    # Use provided screenshot or extract from state
    if screenshot_data is None:
        screenshot_data = result_state.pop("screenshot", None)
    
    # Store screenshot metadata (without base64 data) for TextContent
    screenshot_metadata = None
    if screenshot_data and not screenshot_data.get("error"):
        screenshot_metadata = {
            "format": screenshot_data.get("format", "base64_png"),
            "width": screenshot_data.get("width"),
            "height": screenshot_data.get("height")
        }
    
    # Add screenshot metadata to result if present
    if screenshot_metadata:
        result["screenshot"] = screenshot_metadata
    
    from computer_mcp.runtime_contract import describe
    result.setdefault('runtime_contract', describe(include_schema=False))

    # Merge result with remaining state
    result.update(result_state)
    
    # Build response list
    response: list[Union[TextContent, ImageContent]] = []
    
    # Add ImageContent if screenshot is enabled and valid
    if state.config.get("observe_screen", True) and screenshot_data:
        image_content = screenshot_to_image_content(screenshot_data)
        if image_content:
            response.append(image_content)

    # Extra crops from screenshot(regions=[...]) travel as their own images.
    extras = result.pop("_images", None) or []
    for shot in extras[1:]:
        try:
            extra_content = screenshot_to_image_content(shot)
        except Exception:                                # noqa: BLE001
            extra_content = None
        if extra_content:
            response.append(extra_content)
    
    # Add TextContent with the result data
    response.append(TextContent(type="text", text=json.dumps(result)))
    
    return response

