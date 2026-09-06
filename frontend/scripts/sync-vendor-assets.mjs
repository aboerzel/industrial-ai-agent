import { copyFile, mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const destination = fileURLToPath(new URL("../js/vendor/", import.meta.url));

await mkdir(destination, { recursive: true });
await Promise.all([
  copyFile(
    fileURLToPath(new URL("../node_modules/marked/lib/marked.esm.js", import.meta.url)),
    fileURLToPath(new URL("../js/vendor/marked.esm.js", import.meta.url)),
  ),
  copyFile(
    fileURLToPath(new URL("../node_modules/dompurify/dist/purify.es.mjs", import.meta.url)),
    fileURLToPath(new URL("../js/vendor/purify.es.mjs", import.meta.url)),
  ),
]);
