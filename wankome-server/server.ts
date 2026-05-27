import { appendFile, mkdir } from "node:fs/promises";
import { join } from "node:path";

const LOG_DIR = join(import.meta.dir, "..", "log");
const PORT = 11180;

async function writeLog(message: string): Promise<void> {
  const now = new Date();
  const jst = new Date(now.getTime() + 9 * 60 * 60 * 1000);
  const dateStr = jst.toISOString().slice(0, 10); // YYYY-MM-DD (JST)
  const timestamp = jst.toISOString().replace("T", " ").slice(0, 23);
  const logFile = join(LOG_DIR, `wankome-server-${dateStr}.log`);

  await mkdir(LOG_DIR, { recursive: true });
  await appendFile(logFile, `[${timestamp}] ${message}\n`, "utf-8");
}

function log(level: "INFO" | "WARN" | "ERROR", message: string): void {
  const now = new Date();
  const timestamp = new Date(now.getTime() + 9 * 60 * 60 * 1000)
    .toISOString()
    .replace("T", " ")
    .slice(0, 23);
  console.log(`[${timestamp}] [${level}] ${message}`);
  writeLog(`[${level}] ${message}`).catch((e) =>
    console.error("ログ書き込みエラー:", e)
  );
}

const server = Bun.serve({
  port: PORT,
  hostname: "0.0.0.0",

  async fetch(req) {
    const url = new URL(req.url);
    const clientIP =
      req.headers.get("x-forwarded-for") ?? server.requestIP(req)?.address ?? "unknown";

    // POST /api/wordparty/:id のみ受け付ける
    const match = url.pathname.match(/^\/api\/wordparty\/([^/]+)$/);
    if (req.method === "POST" && match) {
      const wordpartyId = match[1];
      const bodyText = await req.text().catch(() => "");

      log(
        "INFO",
        `受信: POST /api/wordparty/${wordpartyId} from=${clientIP} body=${bodyText || "(empty)"}`
      );

      return new Response(
        JSON.stringify({ ok: true, id: wordpartyId }),
        {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }
      );
    }

    log("WARN", `未対応リクエスト: ${req.method} ${url.pathname} from=${clientIP}`);
    return new Response(
      JSON.stringify({ ok: false, error: "Not Found" }),
      {
        status: 404,
        headers: { "Content-Type": "application/json" },
      }
    );
  },
});

log("INFO", `わんこめモックサーバー起動: http://0.0.0.0:${PORT}`);
log("INFO", `ログ出力先: ${LOG_DIR}/wankome-server-YYYY-MM-DD.log`);
