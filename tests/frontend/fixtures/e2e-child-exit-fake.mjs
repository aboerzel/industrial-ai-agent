import childProcess from "node:child_process";
import { EventEmitter } from "node:events";
import { syncBuiltinESMExports } from "node:module";

// Exercise wrapper propagation without starting a browser or model-backed child.
childProcess.spawn = (_executable, arguments_) => {
  const child = new EventEmitter();
  queueMicrotask(() => child.emit("exit", arguments_.includes("--aggregate") ? 1 : 0));
  return child;
};
syncBuiltinESMExports();
