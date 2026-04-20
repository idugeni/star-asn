export interface TelegramWebApp {
    ready: () => void;
    expand: () => void;
    initDataUnsafe: {
        user?: {
            id: number;
            first_name: string;
            username?: string;
        };
    };
    HapticFeedback: {
        impactOccurred: (style: 'light' | 'medium' | 'heavy' | 'rigid' | 'soft') => void;
    };
}

export interface AttendanceLog {
    id: string;
    nip: string;
    action: 'HADIR' | 'PULANG';
    status: 'SUCCESS' | 'FAILED';
    timestamp: string;
    message?: string;
}

export interface SystemStats {
    total: number;
    uptime: string;
    security: string;
    clusters: number;
    activity: number[];
}
