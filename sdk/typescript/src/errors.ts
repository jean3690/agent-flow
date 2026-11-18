export class AgentFlowError extends Error {}

export class ApiError extends AgentFlowError {
  code: any;
  raw: any;

  constructor(code: any, message: string, raw?: any) {
    super("[" + code + "] " + message);
    this.code = code;
    this.raw = raw;
  }
}
