// The decision inside the panel's Stop button.
//
// Stop does one of two things, and the choice is the whole of it: when a
// write is waiting for the reader's approval, Stop rejects it; when a turn
// is running, Stop aborts the waits.  A write that is waiting is a turn
// that is still running, so rejecting it is not enough — the turn has to
// stop as well, otherwise it takes a second press.
//
// The decision is here and not in the component because it *is* a
// decision, and a decision that lives in a component is a decision nobody
// can test: this file is read by plain node, with no Vue and no Desk.
//
// Pure: no `frappe`, no DOM, so it is tested under plain node.

/**
 * What Stop should do for the current state.
 *
 * @param {{hasApproval?: boolean, mayStop?: boolean}} input
 * @returns {{rejectApprovals: boolean, abortWaits: boolean}}
 */
export function stopPlan(input) {
	const data = input || {};
	const hasApproval = !!data.hasApproval;
	const mayStop = !!data.mayStop;
	return {
		// Reject every pending approval when one is waiting.
		rejectApprovals: hasApproval,
		// Abort the waits whenever a turn may be stopped.  This is true
		// even when an approval was just rejected: rejecting only tells
		// the model to carry on to its next round.
		abortWaits: mayStop,
	};
}