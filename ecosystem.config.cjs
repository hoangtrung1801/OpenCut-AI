const path = require("node:path");

const projectRoot = __dirname;
const pythonLauncher = path.join(
    projectRoot,
    "scripts/start-python-service.sh",
);
const logDirectory = path.join(projectRoot, "pm2-logs");

const logOptions = (name) => ({
    out_file: path.join(logDirectory, `${name}-out.log`),
    error_file: path.join(logDirectory, `${name}-error.log`),
});

const baseOptions = {
    cwd: projectRoot,
    interpreter: "bash",
    exec_mode: "fork",
    instances: 1,
    autorestart: false,
    restart_delay: 2000,
    kill_timeout: 5000,
    time: true,
    merge_logs: true,
    log_date_format: "YYYY-MM-DD HH:mm:ss Z",
};

const pythonServices = [
    ["whisper", "whisper-service", 8421],
    ["tts", "tts-service", 8422],
    ["image", "image-service", 8423],
    ["speaker", "speaker-service", 8424],
    ["clip", "clip-service", 8426],
    ["turboquant", "turboquant-service", 8430],
].map(([name, service, port]) => ({
    ...baseOptions,
    ...logOptions(`opencut-${name}`),
    name: `opencut-${name}`,
    script: pythonLauncher,
    args: `${service} ${port}`,
    env: {
        PORT: String(port),
        PYTHONUNBUFFERED: "1",
    },
}));

module.exports = {
    apps: [
        {
            ...baseOptions,
            ...logOptions("opencut-web"),
            name: "opencut-web",
            script: path.join(projectRoot, "scripts/start-web.sh"),
            env: {
                PORT: "3000",
            },
        },
        {
            ...baseOptions,
            ...logOptions("opencut-ai-backend"),
            name: "opencut-ai-backend",
            script: path.join(projectRoot, "scripts/start-ai-backend.sh"),
            env: {
                OPENCUTAI_HOST: "127.0.0.1",
                OPENCUTAI_PORT: "8420",
                PYTHONUNBUFFERED: "1",
            },
        },
        ...pythonServices,
    ],
};
