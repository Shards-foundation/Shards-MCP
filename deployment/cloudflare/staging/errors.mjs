// Only locally defined reason codes may enter acceptance receipts.
export class GateFailure extends Error {}
export class GateBlocked extends Error {}
export const ensure=(ok,code)=>{if(!ok)throw new GateFailure(code);};
