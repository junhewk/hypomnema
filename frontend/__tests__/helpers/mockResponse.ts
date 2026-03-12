export function mockJsonResponse(data: object) {
  return {
    ok: true,
    status: 200,
    json: async () => data,
  };
}

export function mockErrorResponse(status: number, statusText: string, body = "") {
  return {
    ok: false,
    status,
    statusText,
    text: async () => body,
  };
}
