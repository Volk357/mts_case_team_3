import { ApiError } from "@/api/client";
import { getDocument, uploadDocument } from "@/api/documents";

type EventListener = (event: ProgressEvent) => void;

class FakeEventTarget {
  private readonly listeners = new Map<string, EventListener[]>();

  addEventListener(type: string, listener: EventListener): void {
    this.listeners.set(type, [...(this.listeners.get(type) ?? []), listener]);
  }

  removeEventListener(type: string, listener: EventListener): void {
    this.listeners.set(
      type,
      (this.listeners.get(type) ?? []).filter((candidate) => candidate !== listener),
    );
  }

  emit(type: string, event = new ProgressEvent(type)): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event);
  }
}

class FakeXMLHttpRequest extends FakeEventTarget {
  static status = 201;
  static response: unknown = {
    document_id: "document-1",
    filename: "report.pdf",
    size_bytes: 3,
    media_type: "application/pdf",
  };
  static lastRequest: FakeXMLHttpRequest | null = null;

  readonly upload = new FakeEventTarget();
  status = FakeXMLHttpRequest.status;
  response: unknown = FakeXMLHttpRequest.response;
  responseType = "";
  method = "";
  url = "";
  body: Document | XMLHttpRequestBodyInit | null = null;

  constructor() {
    super();
    FakeXMLHttpRequest.lastRequest = this;
  }

  open(method: string, url: string): void {
    this.method = method;
    this.url = url;
  }

  setRequestHeader(): void {}

  send(body: Document | XMLHttpRequestBodyInit | null): void {
    this.body = body;
    this.upload.emit(
      "progress",
      new ProgressEvent("progress", { lengthComputable: true, loaded: 5, total: 10 }),
    );
    this.emit("load");
    this.emit("loadend");
  }

  abort(): void {
    this.emit("abort");
    this.emit("loadend");
  }
}

beforeEach(() => {
  FakeXMLHttpRequest.status = 201;
  FakeXMLHttpRequest.response = {
    document_id: "document-1",
    filename: "report.pdf",
    size_bytes: 3,
    media_type: "application/pdf",
  };
  FakeXMLHttpRequest.lastRequest = null;
  vi.stubGlobal("XMLHttpRequest", FakeXMLHttpRequest);
});

afterEach(() => vi.unstubAllGlobals());

it("sends multipart data and reports browser upload progress", async () => {
  const progress: number[] = [];
  const file = new File(["pdf"], "report.pdf", { type: "application/pdf" });

  const result = await uploadDocument(file, (percent) => progress.push(percent));

  expect(result.document_id).toBe("document-1");
  expect(progress).toEqual([50, 100]);
  expect(FakeXMLHttpRequest.lastRequest?.method).toBe("POST");
  expect(FakeXMLHttpRequest.lastRequest?.url).toBe("/api/documents");
  const form = FakeXMLHttpRequest.lastRequest?.body;
  expect(form).toBeInstanceOf(FormData);
  expect((form as FormData).get("document")).toBeInstanceOf(File);
});

it("preserves the API status and safe detail on an upload failure", async () => {
  FakeXMLHttpRequest.status = 422;
  FakeXMLHttpRequest.response = {
    error: {
      code: "DOCUMENT_FORMAT_INVALID",
      message: "The document format is invalid",
      details: [],
    },
  };

  const request = uploadDocument(
    new File(["bad"], "report.pdf", { type: "application/pdf" }),
    () => undefined,
  );

  await expect(request).rejects.toEqual(
    new ApiError("The document format is invalid", 422, "DOCUMENT_FORMAT_INVALID"),
  );
});

it("loads one document through its opaque encoded id", async () => {
  const payload = {
    document_id: "document/id",
    filename: "report.pdf",
    size_bytes: 3,
    media_type: "application/pdf",
    created_at: "2026-09-03T12:00:00.000Z",
  };
  const fetchMock = vi.fn<typeof fetch>().mockResolvedValue(
    new Response(JSON.stringify(payload), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await expect(getDocument("document/id")).resolves.toEqual(payload);
  const [url, init] = fetchMock.mock.calls[0] ?? [];
  expect(url).toBe("/api/documents/document%2Fid");
  expect(new Headers(init?.headers).get("Accept")).toBe("application/json");
});
