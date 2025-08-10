// Connect to your locally running backend
const socket = io("http://localhost:8000", {
  transports: ["websocket"], // prefer websocket; falls back automatically if needed
});

// Connection events
socket.on("connect", () => {
  console.log("[client] connected with id:", socket.id);
  // send a test message to the server
  socket.emit("ping", { hello: "world" });
});

socket.on("pong", (data) => {
  console.log("[client] server replied:", data);
});

socket.on("disconnect", (reason) => {
  console.log("[client] disconnected:", reason);
});
