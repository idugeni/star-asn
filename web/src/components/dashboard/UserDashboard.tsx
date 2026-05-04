import React, { useState, useMemo } from 'react';
import { motion } from 'motion/react';
import { HiOutlineFingerPrint, HiOutlineMapPin, HiOutlineClock, HiOutlineShieldCheck, HiOutlineCpuChip } from "react-icons/hi2";
import { RiScan2Line, RiUserSettingsLine, RiDownloadCloud2Line, RiMapPinRangeLine, RiHistoryLine, RiTerminalBoxLine } from "react-icons/ri";
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
            toast.error('ACCESS_REFUSED: Node coordinates outside operational radius.');
            return;
        }
        
        setIsTriggering(true);
        const apiBase = import.meta.env.VITE_API_URL || '';
        
        const triggerPromise = async () => {
            if (!apiBase) throw new Error("INTERNAL_ERROR: Kernel API endpoint missing.");
            const res = await fetch(`${apiBase}/api/attendance/trigger?nip=${user.nip}`, { method: 'POST' });
            if (!res.ok) throw new Error("NETWORK_FAILURE: Link connection timed out.");
            return await res.json();
        };

        toast.promise(triggerPromise(), {
            loading: 'Relaying Neural Presence Signal...',
            success: (data: { message: string }) => {
                setIsTriggering(false);
                return `TRANSMISSION_COMPLETE: ${data.message}`;
            },
            error: (err) => {
                setIsTriggering(false);
                return `GATEWAY_ERROR: ${err.message}`;
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
        a.setAttribute('download', `manifest_trace_${user.nip}.csv`);
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        toast.success('System manifest trace exported');
    };

    const renderHeader = (title: string, sub: string, BadgeIcon: React.ElementType, badgeText: string, ActionIcon?: React.ElementType, action?: () => void) => (
        <header className="flex justify-between items-center mb-8">
            <div className="space-y-2">
                <Badge variant="outline" className="gap-1.5 bg-primary/5 text-primary border-primary/20 px-2.5 py-1 uppercase tracking-[0.2em] font-black text-[8px] animate-pulse">
                    <BadgeIcon className="h-3 w-3" /> {badgeText}
                </Badge>
                <div className="space-y-1">
                    <h1 className="text-3xl font-black tracking-tighter text-white uppercase italic leading-none">
                        {title.split('.')[0]}<span className="text-primary">.{title.split('.')[1]}</span>
                    </h1>
                    <p className="text-[8px] font-black uppercase tracking-[0.4em] text-muted-foreground italic opacity-40">
                        {sub}
                    </p>
                </div>
            </div>
            {ActionIcon && (
                <motion.button 
                    whileHover={{ scale: 1.05 }}
                    whileTap={{ scale: 0.95 }}
                    onClick={action} 
                    className="w-12 h-12 rounded-2xl bg-white/5 border border-white/10 flex items-center justify-center text-white hover:bg-white/10 transition-colors shadow-lg"
                >
                    <ActionIcon className="h-5 w-5" />
                </motion.button>
            )}
        </header>
    );

    if (activeTab === 'records') {
        return (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderHeader('TEMPORAL.LOGS', 'Infrastructure Event Feed', RiHistoryLine, 'READ_ONLY_TRACE', RiDownloadCloud2Line, exportLogs)}
                
                <Card className="glass-premium border-primary/20 bg-slate-950/80 rounded-[28px] overflow-hidden shadow-[0_0_40px_rgba(0,0,0,0.5)]">
                    <div className="bg-white/5 px-4 py-2 border-b border-white/5 flex justify-between items-center">
                        <div className="flex gap-1.5">
                            <div className="w-1.5 h-1.5 rounded-full bg-red-500/50" />
                            <div className="w-1.5 h-1.5 rounded-full bg-amber-500/50" />
                            <div className="w-1.5 h-1.5 rounded-full bg-emerald-500/50" />
                        </div>
                        <p className="text-[7px] font-black text-muted-foreground/40 uppercase tracking-[0.3em]">Access_Trace_v2.1</p>
                    </div>
                    <div className="p-4 font-mono text-[9px] leading-relaxed space-y-1.5">
                        {logs.length > 0 ? logs.map((log, i) => (
                            <motion.div
                                key={i}
                                initial={{ opacity: 0, x: -5 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ delay: i * 0.02 }}
                                className="flex gap-3 group"
                            >
                                <span className="text-muted-foreground/30 shrink-0">[{new Date(log.timestamp).toLocaleTimeString([], { hour12: false })}]</span>
                                <span className={cn(
                                    "font-black shrink-0",
                                    ['success', 'ok'].includes(log.status) ? "text-emerald-500/80" : "text-destructive"
                                )}>
                                    {['success', 'ok'].includes(log.status) ? '>> AUTH' : '!! FAIL'}
                                </span>
                                <span className="text-white/80 flex-1 truncate uppercase tracking-tight">
                                    {log.action} <span className="text-primary/40 text-[7px]">{new Date(log.timestamp).toLocaleDateString()}</span>
                                </span>
                            </motion.div>
                        )) : (
                            <div className="h-full flex flex-col items-center justify-center opacity-30 py-20">
                                <RiTerminalBoxLine className="h-10 w-10 mb-4" />
                                <p className="uppercase tracking-[0.2em] text-[8px]">No_Trace_Detected...</p>
                            </div>
                        )}
                        
                        <div className="mt-6 pt-4 border-t border-white/5 opacity-20 italic text-[7px] uppercase tracking-widest text-center">
                            End of transmission sequence
                        </div>
                    </div>
                </Card>
            </div>
        );
    }

    if (activeTab === 'config') {
        return (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderHeader('NODE.CFG', 'Identity Parameters', RiUserSettingsLine, 'SECURITY_LEVEL_4')}
                
                <Card className="glass-premium border-primary/10 p-6 space-y-6 rounded-[32px]">
                    <div className="flex items-center gap-5 border-b border-white/10 pb-6">
                        <div className="w-16 h-16 rounded-[24px] bg-primary/10 border border-primary/20 flex items-center justify-center text-primary shadow-2xl shadow-primary/20">
                            <RiUserSettingsLine size={32} />
                        </div>
                        <div className="space-y-1">
                            <p className="text-base font-black text-white uppercase tracking-tight leading-none">{user.nama}</p>
                            <p className="text-[10px] text-primary font-mono font-bold tracking-[0.2em] opacity-80 uppercase">ACCESS_ID://{user.nip}</p>
                            <Badge variant="outline" className="text-[7px] font-black border-primary/20 text-primary bg-primary/5 uppercase h-4">STATIONARY_NODE</Badge>
                        </div>
                    </div>
                    
                    <div className="grid gap-3">
                        <div className="p-4 rounded-2xl bg-white/5 border border-white/5 space-y-3">
                            <div className="flex justify-between items-center text-[8px] font-black text-muted-foreground uppercase tracking-widest">
                                <span>Biometric_Confidence</span>
                                <span className="text-emerald-500">99.8%</span>
                            </div>
                            <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                                <motion.div initial={{ width: 0 }} animate={{ width: '99.8%' }} className="h-full bg-emerald-500 shadow-[0_0_10px_rgba(16,185,129,0.5)]" />
                            </div>
                        </div>
                        <Button variant="outline" className="w-full h-8 text-[9px] font-black uppercase tracking-[0.2em] border-white/10 bg-white/5 hover:bg-white/10 rounded-xl">
                            Recalibrate Neural Hash
                        </Button>
                    </div>
                </Card>
            </div>
        );
    }

    return (
        <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
            <header className="flex justify-between items-start">
                <div className="space-y-1">
                    <motion.div initial={{ opacity: 0, x: -10 }} animate={{ opacity: 1, x: 0 }}>
                        <Badge variant="outline" className="gap-1.5 border-emerald-500/20 text-emerald-500 bg-emerald-500/10 px-3 py-1 text-[9px] font-black tracking-widest rounded-full">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
                            SECURE_LINK_ACTIVE
                        </Badge>
                    </motion.div>
                    <h1 className="text-3xl font-black tracking-tighter text-white uppercase italic leading-none pt-2">
                        System.<span className="text-primary">Greet</span>(<span className="opacity-50">{user.nama.split(' ')[0]}</span>)
                    </h1>
                </div>
                <div className="text-right space-y-1">
                    <p className="text-[8px] font-black text-muted-foreground/40 uppercase tracking-[0.2em]">Matrix_Latency</p>
                    <p className="text-xs font-black text-primary italic leading-none drop-shadow-md">12MS</p>
                </div>
            </header>

            {/* Location Guard Module */}
            <Card className="glass-premium border-primary/10 p-6 relative overflow-hidden group rounded-[32px] shadow-[0_0_30px_rgba(0,0,0,0.2)]">
                <div className={cn(
                    "absolute -right-10 -top-10 w-40 h-40 blur-[60px] -z-10 opacity-20 transition-all duration-700",
                    isInRange ? "bg-emerald-500" : "bg-destructive"
                )} />
                <div className="flex justify-between items-center">
                    <div className="space-y-1">
                        <div className="flex items-center gap-3">
                            <div className={cn("p-2 rounded-xl border transition-colors", isInRange ? "bg-emerald-500/10 border-emerald-500/20 text-emerald-500" : "bg-destructive/10 border-destructive/20 text-destructive")}>
                                <RiMapPinRangeLine className="h-5 w-5" />
                            </div>
                            <div>
                                <p className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/60">Location Guard</p>
                                <p className={cn(
                                    "text-lg font-black uppercase italic tracking-tighter leading-none mt-0.5",
                                    isInRange ? "text-emerald-500 drop-shadow-[0_0_8px_rgba(16,185,129,0.3)]" : "text-destructive"
                                )}>
                                    {isInRange ? 'Authorized' : distance === null ? 'Locating Node...' : `OUT_OF_BOUNDS`}
                                </p>
                            </div>
                        </div>
                    </div>
                    <div className="text-right">
                        <p className="text-[10px] font-black text-white tabular-nums tracking-tighter italic">
                             {distance !== null ? `${Math.round(distance)}m` : '--m'}
                        </p>
                        <p className="text-[7px] font-black uppercase text-muted-foreground/30 tracking-widest mt-0.5">Distance</p>
                    </div>
                </div>
                {!isInRange && distance !== null && (
                    <div className="mt-5 p-3 rounded-xl bg-destructive/5 border border-destructive/10">
                        <p className="text-[8px] text-destructive/80 font-black uppercase tracking-widest leading-relaxed text-center italic">
                            Operational Radius Breached. Approach Section: {user.upts?.nama_upt}.
                        </p>
                    </div>
                )}
            </Card>

            <div className="grid grid-cols-2 gap-4">
                <Card className="glass-premium border-primary/10 p-5 space-y-3 relative overflow-hidden group border-white/5 rounded-[28px]">
                    <HiOutlineClock className="h-6 w-6 text-primary absolute -right-1 -bottom-1 opacity-10 group-hover:scale-110 transition-transform" />
                    <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">Uptime_Session</p>
                    <p className="text-3xl font-black text-white tracking-tighter leading-none tabular-nums italic">04:12</p>
                </Card>
                <Card className="glass-premium border-primary/10 p-5 space-y-3 relative overflow-hidden group border-white/5 rounded-[28px]">
                    <HiOutlineShieldCheck className="h-6 w-6 text-emerald-500 absolute -right-1 -bottom-1 opacity-10 group-hover:scale-110 transition-transform" />
                    <p className="text-[9px] font-black uppercase tracking-widest text-muted-foreground/60">Verified_Ops</p>
                    <p className="text-3xl font-black text-white tracking-tighter leading-none italic">{stats.total}</p>
                </Card>
            </div>

            <motion.div initial={{ y: 20, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={{ delay: 0.2 }} className="relative group">
                <Card className="glass-premium overflow-hidden border-primary/20 shadow-premium rounded-[40px]">
                    <CardContent className="p-8 space-y-10">
                        <div className="flex justify-between items-center border-b border-white/10 pb-8">
                            <div className="space-y-1">
                                <p className="text-[10px] font-black uppercase tracking-[0.3em] text-muted-foreground/40">Neural_Hash</p>
                                <div className="flex items-center gap-2">
                                    <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.8)]" />
                                    <p className="text-2xl font-black italic uppercase text-white tracking-tighter">ACTIVE</p>
                                </div>
                            </div>
                            <div className="text-right space-y-1">
                                <p className="text-3xl font-black text-primary tracking-tighter leading-none text-glow">{user.cron_in}</p>
                                <p className="text-[8px] font-black text-muted-foreground/30 uppercase tracking-[0.2em] italic">Sequence_A_Start</p>
                            </div>
                        </div>
                        
                        <Button 
                            disabled={isTriggering || !isInRange}
                            onClick={handlePresensi}
                            className="w-full h-10 rounded-xl font-black uppercase tracking-[0.2em] text-[10px] shadow-xl shadow-primary/30 hover:shadow-primary/50 transition-all hover:scale-[1.02] active:scale-[0.98] relative overflow-hidden group disabled:grayscale disabled:opacity-40"
                        >
                            <div className="absolute inset-0 bg-gradient-to-r from-primary to-blue-400 group-hover:opacity-90 transition-opacity" />
                            <div className="relative flex items-center justify-center">
                                <RiScan2Line className={cn("mr-3 h-4 w-4 transition-transform group-hover:scale-110", isTriggering && "animate-spin")} /> 
                                {isTriggering ? 'TRANSMITTING...' : 'INITIALIZE_EXEC'}
                            </div>
                        </Button>
                    </CardContent>
                </Card>
            </motion.div>

            <Card className="glass-premium border-primary/10 p-6 shadow-2xl rounded-[32px]">
                <ActivityHeatmap data={stats.activity} />
            </Card>
        </div>
    );
};
