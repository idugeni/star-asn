export interface User {
    nama: string;
    nip: string;
    role: string;
    is_admin: boolean;
    cron_in: string;
    cron_out: string;
    upts?: {
        nama_upt: string;
        latitude: number;
        longitude: number;
    };
}
