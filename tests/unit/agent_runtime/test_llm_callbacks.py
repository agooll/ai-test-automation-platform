import pytest

from testteller.agent_runtime.llm_callbacks import AgentPlan, AgentReview, StructuredLLMCallbacks


class FakeStructuredModel:
    def __init__(self, value):
        self.value = value

    def with_structured_output(self, schema):
        return FakeInvoker(self.value)


class FakeInvoker:
    def __init__(self, value):
        self.value = value

    def invoke(self, prompt):
        return self.value


@pytest.mark.asyncio
async def test_structured_callbacks_return_validated_dicts():
    callbacks = StructuredLLMCallbacks(FakeStructuredModel(AgentPlan(goal="g", steps=["execute"])))
    plan = await callbacks.planner({"requirement": "g"})
    assert plan["steps"] == ["execute"]

    callbacks = StructuredLLMCallbacks(FakeStructuredModel(AgentReview(status="pass")))
    review = await callbacks.reviewer({"execution_result": {"passed": True}})
    assert review["status"] == "pass"
