import net from "node:net";

// Keep CLI contention regressions isolated from the machine's real GPU reservation.
const listen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {
  if (args[0]?.port === 46233) args[0] = { ...args[0], port: Number(process.env.TEST_RUNTIME_PORT) };
  return listen.apply(this, args);
};
