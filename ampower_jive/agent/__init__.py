"""AmPower Jive Agent Module"""

from .graph import JiveAgent, get_agent
from .rag_service import RagService, build_rag_index, enqueue_rag_index_build
from .rag_resolution import RagResolver, resolve_rag_target
from .vector_database_service import (
    MultiVectorDatabaseRagService,
    VectorDatabaseRagService,
    build_vector_database_index,
    enqueue_vector_database_index_build,
)

try:
    from .agent_graph import AgentModeGraph
except ImportError:
    AgentModeGraph = None

try:
    from .tools import get_available_tools
except ImportError:
    get_available_tools = None

try:
    from .agent_tools import get_agent_tools
except ImportError:
    get_agent_tools = None

try:
    from .insights_graph import InsightsAgent, get_insights_agent
except ImportError:
    InsightsAgent = None
    get_insights_agent = None

try:
    from .insights_tools import is_insights_installed, INSIGHTS_TOOLS
except ImportError:
    is_insights_installed = None
    INSIGHTS_TOOLS = None
