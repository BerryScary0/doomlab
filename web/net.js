// Connect to backend
const socket = io("http://localhost:8000"); // no transports override
window.__socket = socket;

socket.on("connect", () => {
  console.log("[client] connected:", socket.id);
  socket.emit("ping", { hello: "world" });
});

socket.on("pong", (data) => console.log("[client] pong:", data));
socket.on("snapshot", (snap) => { window.__lastSnapshot = snap; });

socket.on("disconnect", (reason) => {
  console.log("[client] disconnected:", reason);
});
