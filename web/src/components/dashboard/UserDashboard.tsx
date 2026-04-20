import React, { useState, useMemo } from 'react';
import { motion } from 'motion/react';
import { HiOutlineFingerPrint, HiOutlineMapPin, HiOutlineClock, HiOutlineShieldCheck, HiOutlineCpuChip } from "react-icons/hi2";
import { RiScan2Line, RiUserSettingsLine, RiDownloadCloud2Line, RiMapPinRangeLine } from "react-icons/ri";
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { User } from '@/types/user';
import { ActivityHeatmap } from '@/components/charts/ActivityHeatmap';
import { AttendanceLog, SystemStats } from '@/types/system';
import { cn } from '@/lib/utils';

interface UserDashboardProps {
    user: User;
    activeTab: string;
    logs: AttendanceLog[];
    stats: SystemStats;
    userLocation: { lat: number, lng: number } | null;
}

// Haversine formula to calculate distance in meters
const calculateDistance = (lat1: number, lon1: number, lat2: number, lon2: number) => {
    const R = 6371e3; // metres
    const φ1 = lat1 * Math.PI/180;
    const φ2 = lat2 * Math.PI/180;
    const Δφ = (lat2-lat1) * Math.PI/180;
    const Δλ = (lon2-lon1) * Math.PI/180;

    const a = Math.sin(Δφ/2) * Math.sin(Δφ/2) +
            Math.cos(φ1) * Math.cos(φ2) *
            Math.sin(Δλ/2) * Math.sin(Δλ/2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1-a));

    return R * c;
};

export const UserDashboard = ({ user, activeTab, logs, stats, userLocation }: UserDashboardProps) => {
    const [isTriggering, setIsTriggering] = useState(false);

    const distance = useMemo(() => {
        if (!userLocation || !user.upts?.latitude) return null;
        return calculateDistance(
            userLocation.lat, userLocation.lng,
            user.upts.latitude, user.upts.longitude
        );
    }, [userLocation, user]);

    const isInRange = distance !== null && distance <= 100;

    const handlePresensi = async () => {
        if (!isInRange) {
            toast.error('Gagal: Anda berada di luar radius operasional UPT.');
            return;
        }
        
        setIsTriggering(true);
        const apiBase = import.meta.env.VITE_API_URL || '';
        
        const triggerPromise = async () => {
            if (!apiBase) throw new Error("API URL belum diatur!");
            const res = await fetch(`${apiBase}/api/attendance/trigger?nip=${user.nip}`, { method: 'POST' });
            if (!res.ok) throw new Error("Gagal menghubungi server.");
            return await res.json();
        };

        toast.promise(triggerPromise(), {
            loading: 'Mengirim sinyal ke Star-ASN Engine...',
            success: (data: { message: string }) => {
                setIsTriggering(false);
                return `SUCCESS: ${data.message}`;
            },
            error: (err) => {
                setIsTriggering(false);
                return `FAILED: ${err.message}`;
            },
        });
    };

    const exportLogs = () => {
        const csv = [
            ['ID', 'NIP', 'Action', 'Status', 'Timestamp'],
            ...logs.map(l => [l.id, l.nip, l.action, l.status, l.timestamp])
        ].map(e => e.join(",")).join("\n");

        const blob = new Blob([csv], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.setAttribute('hidden', '');
        a.setAttribute('href', url);
        a.setAttribute('download', `attendance_logs_${user.nip}.csv`);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        toast.success('Audit trail exported successfully');
    };

    if (activeTab === 'records') {
        return (
            <div className="space-y-6">
                <header className="flex justify-between items-center">
                    <div>
                        <h2 className="text-2xl font-black tracking-tighter text-white uppercase italic">
                            Temporal.<span className="text-primary">Logs</span>
                        </h2>
                        <p className="text-[8px] font-bold text-muted-foreground uppercase tracking-widest mt-1 opacity-60">Verification History Array</p>
                    </div>
                    <Button variant="outline" size="sm" onClick={exportLogs} className="h-8 text-[8px] font-black uppercase border-white/5 bg-white/5">
                        <RiDownloadCloud2Line className="mr-1.5 h-3 w-3" /> Export CSV
                    </Button>
                </header>
                <div className="grid gap-3">
                    {logs.length > 0 ? logs.map((log, i) => (
                        <Card key={i} className="bg-card/40 border-border/50 p-4 flex justify-between items-center group hover:bg-accent/5 transition-all">
                            <div className="flex items-center gap-3">
                                <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center text-primary">
                                    <HiOutlineFingerPrint size={16} />
                                </div>
                                <div>
                                    <p className="text-[10px] font-black text-white uppercase">{log.action}</p>
                                    <p className="text-[8px] text-muted-foreground uppercase opacity-50">
                                        {new Date(log.timestamp).toLocaleString('id-ID', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })}
                                    </p>
                                </div>
                            </div>
                            <Badge variant="outline" className={cn(
                                "text-[7px] font-bold px-2 py-0.5 border-none",
                                log.status === 'SUCCESS' ? "text-emerald-500 bg-emerald-500/10" : "text-amber-500 bg-amber-500/10"
                            )}>
                                {log.status}
                            </Badge>
                        </Card>
                    )) : (
                        <div className="text-center py-10 opacity-30 text-xs uppercase tracking-widest font-black">No Records Found</div>
                    )}
                </div>
            </div>
        );
    }

    if (activeTab === 'config') {
        return (
            <div className="space-y-6">
                <header>
                    <h2 className="text-2xl font-black tracking-tighter text-white uppercase italic">
                        Node.<span className="text-primary">Config</span>
                    </h2>
                    <p className="text-[8px] font-bold text-muted-foreground uppercase tracking-widest mt-1 opacity-60">Identity & Biometric Parameters</p>
                </header>
                <Card className="bg-card/40 border-border/50 p-5 space-y-5">
                    <div className="flex items-center gap-3 border-b border-white/5 pb-5">
                        <div className="w-12 h-12 rounded-xl bg-secondary flex items-center justify-center text-muted-foreground">
                            <RiUserSettingsLine size={24} />
                        </div>
                        <div>
                            <p className="text-xs font-black text-white">{user.nama}</p>
                            <p className="text-[9px] text-muted-foreground font-mono">NIP: {user.nip}</p>
                        </div>
                    </div>
                    <div className="grid gap-2">
                        <Button variant="outline" className="w-full h-10 text-[9px] font-black uppercase tracking-widest border-white/10 hover:bg-primary/5">
                            Re-calibrate Biometrics
                        </Button>
                    </div>
                </Card>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            <header className="flex justify-between items-start">
                <div className="space-y-1">
                    <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}>
                        <Badge variant="outline" className="gap-1.5 border-emerald-500/20 text-emerald-500 bg-emerald-500/5 px-2 py-0.5 text-[8px] font-black">
                            <span className="w-1 h-1 rounded-full bg-emerald-500 animate-pulse" />
                            CORE_READY
                        </Badge>
                    </motion.div>
                    <h1 className="text-2xl font-black tracking-tighter text-white">
                        System.<span className="text-primary">Greet</span>({user.nama.split(' ')[0]})
                    </h1>
                </div>
                <div className="text-right">
                    <p className="text-[7px] font-black text-muted-foreground uppercase">Network_Latency</p>
                    <p className="text-[10px] font-black text-amber-500">12MS</p>
                </div>
            </header>

            {/* Location Guard Module */}
            <Card className="bg-card/40 border-border/10 p-5 relative overflow-hidden group">
                <div className={cn(
                    "absolute top-0 right-0 w-32 h-32 blur-[50px] -z-10 opacity-20 transition-colors",
                    isInRange ? "bg-emerald-500" : "bg-destructive"
                )} />
                <div className="flex justify-between items-center">
                    <div className="space-y-1">
                        <div className="flex items-center gap-2">
                            <RiMapPinRangeLine className={cn("h-4 w-4", isInRange ? "text-emerald-500" : "text-destructive")} />
                            <p className="text-[9px] font-black uppercase tracking-widest text-foreground">Location Guard</p>
                        </div>
                        <p className={cn(
                            "text-xs font-black uppercase italic tracking-tighter leading-none mt-1",
                            isInRange ? "text-emerald-500" : "text-destructive"
                        )}>
                            {isInRange ? 'In Range (Authorized)' : distance === null ? 'Locating Node...' : `Out of Range (${Math.round(distance)}m)`}
                        </p>
                    </div>
                    <Badge variant="outline" className={cn(
                        "text-[7px] font-black uppercase h-5 border-none",
                        isInRange ? "bg-emerald-500/5 text-emerald-500" : "bg-destructive/5 text-destructive"
                    )}>
                        {isInRange ? 'TUNNEL_OPEN' : 'LOCKED'}
                    </Badge>
                </div>
                {!isInRange && distance !== null && (
                    <p className="text-[7px] text-muted-foreground opacity-50 mt-2 font-medium italic">Anda harus berada dalam radius 100m dari Kantor {user.upts?.nama_upt}.</p>
                )}
            </Card>

            <div className="grid grid-cols-2 gap-3">
                <Card className="bg-card/40 border-border/50 p-4 space-y-2">
                    <HiOutlineClock className="h-4 w-4 text-primary" />
                    <p className="text-[7px] font-black uppercase text-muted-foreground">Session_Timer</p>
                    <p className="text-xl font-black text-foreground tabular-nums">04:12</p>
                </Card>
                <Card className="bg-card/40 border-border/50 p-4 space-y-2">
                    <HiOutlineShieldCheck className="h-4 w-4 text-emerald-500" />
                    <p className="text-[7px] font-black uppercase text-muted-foreground">Total_Audit</p>
                    <p className="text-xl font-black text-foreground">{stats.total}</p>
                </Card>
            </div>

            <motion.div initial={{ y: 15, opacity: 0 }} animate={{ y: 0, opacity: 1 }} className="relative group">
                <Card className="glass overflow-hidden border-white/5 shadow-premium">
                    <CardContent className="p-6 space-y-6">
                        <div className="flex justify-between items-center border-b border-border/20 pb-6">
                            <div className="space-y-0.5">
                                <p className="text-[8px] font-black uppercase tracking-[0.2em] text-muted-foreground">Neural Hash</p>
                                <p className="text-xl font-black italic uppercase text-white tracking-tight">ACTIVE</p>
                            </div>
                            <div className="text-right">
                                <p className="text-2xl font-black text-primary tracking-tighter leading-none">{user.cron_in}</p>
                                <p className="text-[7px] font-bold text-muted-foreground uppercase mt-1 italic">Sequence_A</p>
                            </div>
                        </div>
                        <Button 
                            disabled={isTriggering || !isInRange}
                            onClick={handlePresensi}
                            className="w-full h-14 text-sm font-black uppercase tracking-[0.3em] rounded-xl group transition-all relative overflow-hidden active:scale-95 disabled:grayscale"
                        >
                            <RiScan2Line className={cn("mr-3 h-5 w-5", isTriggering && "animate-spin")} /> 
                            {isTriggering ? 'PROCESS...' : 'EXEC_INITIALIZE'}
                        </Button>
                    </CardContent>
                </Card>
            </motion.div>

            <Card className="bg-card/30 border-border/50 p-4 shadow-xl">
                <ActivityHeatmap data={stats.activity} />
            </Card>
        </div>
    );
};
