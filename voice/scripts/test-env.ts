// Imported first by test.ts. ES imports run before the importing file's own lines, so setting these in test.ts
// itself came too late: config.ts had already read .env (real keys) and CONTROLLER_URL (the live :8000).
process.env.VOICE_NO_KEYS = process.env.VOICE_NO_KEYS || "1";
process.env.CONTROLLER_URL = process.env.CONTROLLER_URL || "http://127.0.0.1:3029";
process.env.VISION_URL = process.env.VISION_URL || "http://127.0.0.1:3029";  // never the live vision on 8001
