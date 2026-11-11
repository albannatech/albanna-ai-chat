import assert from "node:assert";
import { stopPlan } from "../../albanna_ai_chat/public/js/lib/stop.mjs";

// No approval pending: Stop aborts the waits, and rejects nothing.
{
	const plan = stopPlan({ hasApproval: false, mayStop: true });
	assert.equal(plan.rejectApprovals, false);
	assert.equal(plan.abortWaits, true);
}

// An approval pending: Stop rejects it AND aborts the waits.  Rejecting
// alone leaves the turn running, which is the defect this guards against.
{
	const plan = stopPlan({ hasApproval: true, mayStop: true });
	assert.equal(plan.rejectApprovals, true);
	assert.equal(plan.abortWaits, true);
}

// Nothing may be stopped: nothing is aborted, and no approval is rejected
// unless one is pending.
{
	const plan = stopPlan({ hasApproval: false, mayStop: false });
	assert.equal(plan.rejectApprovals, false);
	assert.equal(plan.abortWaits, false);
}