import React, { useState, useMemo } from 'react';
import { motion, AnimatePresence } from 'motion/react';
import { HiOutlineUsers, HiOutlineShieldCheck, HiOutlineGlobeAlt, HiOutlineServerStack, HiOutlineCpuChip, HiOutlineClock } from "react-icons/hi2";
import { RiSearchLine, RiTerminalBoxLine, RiHistoryLine, RiDownloadCloud2Line, RiRefreshLine, RiUserStarLine, RiUserLine, RiDatabase2Line, RiPulseLine, RiToggleLine } from "react-icons/ri";
import { toast } from 'sonner';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { User } from '@/types/user';
import { AttendanceLog, SystemStats } from '@/types/system';
import { cn } from '@/lib/utils';
import { ActivityHeatmap } from '@/components/charts/ActivityHeatmap';

interface AdminDashboardProps {
    _user: User;
    activeTab: string;
    users: User[];
    stats: SystemStats;
    logs: AttendanceLog[];
}

export const AdminDashboard = ({ _user, activeTab, users, stats, logs }: AdminDashboardProps) => {
    const [searchQuery, setSearchQuery] = useState('');
    const [filterRole, setFilterRole] = useState<'all' | 'admin' | 'user'>('all');
    const [visibleNodes, setVisibleNodes] = useState(10);
    const [visibleLogs, setVisibleLogs] = useState(10);
    const [maintMode, setMaintMode] = useState(false);
    const [selectedUserNip, setSelectedUserNip] = useState<string | null>(null);

    const filteredUsers = useMemo(() => {
        return users.filter(u => {
            const matchesSearch = u.nama.toLowerCase().includes(searchQuery.toLowerCase()) || u.nip.includes(searchQuery);
            const matchesRole = filterRole === 'all' || u.role === filterRole;
            return matchesSearch && matchesRole;
        });
    }, [users, searchQuery, filterRole]);

    const displayedUsers = filteredUsers.slice(0, visibleNodes);
    const displayedLogs = logs.slice(0, visibleLogs);
    const selectedUser = useMemo(
        () => filteredUsers.find((person) => person.nip === selectedUserNip) ?? displayedUsers[0] ?? null,
        [displayedUsers, filteredUsers, selectedUserNip]
    );

    const triggerSync = async () => {
        const id = toast.loading('Synchronizing Nodes...');
        if (typeof (window as any).Telegram?.WebApp?.HapticFeedback !== 'undefined') {
            (window as any).Telegram.WebApp.HapticFeedback.notificationOccurred('success');
        }
        
        const apiBase = import.meta.env.VITE_API_URL || '';
        try {
            await fetch(`${apiBase}/internal/scheduler/sync`, { method: 'POST' });
            toast.success('Matrix Synchronized Successfully.', { id });
        } catch (err) {
            toast.error('Sync Connection Interrupted.', { id });
        }
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

    if (activeTab === 'nodes') {
        return (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderHeader('CORE.MANIFEST', 'Infrastructure Directory', HiOutlineUsers, 'LEVEL_O5_SECURE', RiDownloadCloud2Line)}
                
                <div className="space-y-4">
                    <div className="relative group">
                        <RiSearchLine className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-primary opacity-50 group-focus-within:opacity-100 transition-opacity" />
                        <Input 
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="QUERY NIP/NAME..." 
                            className="h-14 pl-12 rounded-2xl bg-white/5 border-white/10 font-black tracking-widest text-[10px] focus:bg-white/10 focus:border-primary/50 transition-all placeholder:opacity-30"
                        />
                    </div>
                    <div className="flex gap-2 p-1.5 bg-white/5 rounded-2xl border border-white/5">
                        {['all', 'admin', 'user'].map((r) => (
                            <button
                                key={r}
                                onClick={() => setFilterRole(r as any)}
                                className={cn(
                                    "flex-1 py-2 rounded-xl text-[9px] font-black uppercase transition-all tracking-[0.2em]",
                                    filterRole === r ? "bg-primary text-white shadow-[0_0_20px_rgba(59,130,246,0.3)]" : "text-muted-foreground hover:bg-white/5"
                                )}
                            >
                                {r}
                            </button>
                        ))}
                    </div>
                </div>

                <div className="space-y-4">
                    {displayedUsers.map((person, i) => (
                        <motion.button
                            key={person.nip}
                            initial={{ opacity: 0, x: -10 }}
                            animate={{ opacity: 1, x: 0 }}
                            transition={{ delay: i * 0.05 }}
                            onClick={() => setSelectedUserNip(person.nip)}
                            className="w-full text-left focus:outline-none"
                        >
                            <Card className={cn(
                                "glass-premium overflow-hidden transition-all duration-300",
                                selectedUser?.nip === person.nip
                                    ? "border-primary/40 bg-primary/10 scale-[1.02] shadow-2xl shadow-primary/10"
                                    : "hover:bg-white/5"
                            )}>
                                <CardContent className="p-5 space-y-4">
                                    <div className="flex justify-between items-start">
                                        <div className="space-y-1">
                                            <Badge className={cn("text-[7px] font-black border-none px-2 py-0.5 mb-1 tracking-widest", person.role === 'admin' ? "bg-primary text-white" : "bg-emerald-500 text-white")}>
                                                {person.role.toUpperCase()}
                                            </Badge>
                                            <h3 className="text-base font-black text-white uppercase tracking-tight leading-tight">{person.nama}</h3>
                                            <p className="text-[10px] font-mono font-bold text-primary tracking-widest opacity-80">ID://{person.nip}</p>
                                        </div>
                                        <div className="text-right">
                                            <p className="text-[8px] font-mono text-muted-foreground/40 uppercase tracking-widest">NODE_{person.nip.slice(-4)}</p>
                                        </div>
                                    </div>

                                    <div className="grid grid-cols-2 gap-4 pt-4 border-t border-white/10">
                                        <div className="col-span-2">
                                            <p className="text-[8px] font-black uppercase text-muted-foreground/50 mb-1.5 flex items-center gap-2">
                                                <HiOutlineGlobeAlt className="h-3 w-3 text-primary" /> Sector Allocation
                                            </p>
                                            <p className="text-[11px] font-bold text-white uppercase break-words leading-tight">{person.upts?.nama_upt || 'Standalone Regional Node'}</p>
                                        </div>
                                        <div className="space-y-1">
                                            <p className="text-[8px] font-black uppercase text-muted-foreground/50 flex items-center gap-2">
                                                <HiOutlineClock className="h-3 w-3 text-amber-500" /> Ops Window
                                            </p>
                                            <p className="text-[11px] font-mono font-black text-amber-500/90 tracking-tighter">{person.cron_in} - {person.cron_out}</p>
                                        </div>
                                        <div className="flex flex-col items-end">
                                            <p className="text-[8px] font-black uppercase text-muted-foreground/50 mb-1">Status</p>
                                            <div className="flex items-center gap-1.5">
                                                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse shadow-[0_0_8px_rgba(16,185,129,0.5)]" />
                                                <span className="text-[9px] font-black text-emerald-500 uppercase tracking-widest">ACTIVE</span>
                                            </div>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        </motion.button>
                    ))}
                    
                    {filteredUsers.length > visibleNodes && (
                        <Button variant="ghost" onClick={() => setVisibleNodes(v => v + 10)} className="w-full text-[9px] font-black uppercase tracking-[0.3em] text-primary hover:bg-primary/5 py-8 rounded-2xl border border-dashed border-primary/20">
                            Expand Manifest (+{filteredUsers.length - visibleNodes})
                        </Button>
                    )}
                </div>
            </div>
        );
    }

    if (activeTab === 'logs') {
        return (
            <div className="space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderHeader('SYS.LOGS', 'Infrastructure Feed', RiHistoryLine, 'READ_ONLY_ARCHIVE', RiRefreshLine, () => window.location.reload())}
                
                <Card className="glass-premium border-primary/20 bg-slate-950/80 rounded-[28px] overflow-hidden shadow-[0_0_40px_rgba(0,0,0,0.5)]">
                    <div className="bg-white/5 px-4 py-2 border-b border-white/5 flex justify-between items-center">
                        <div className="flex gap-1.5">
                            <div className="w-2 h-2 rounded-full bg-red-500/50" />
                            <div className="w-2 h-2 rounded-full bg-amber-500/50" />
                            <div className="w-2 h-2 rounded-full bg-emerald-500/50" />
                        </div>
                        <p className="text-[7px] font-black text-muted-foreground/40 uppercase tracking-[0.3em]">Matrix_Diagnostics_v4.0</p>
                    </div>
                    <div className="p-4 font-mono text-[9px] leading-relaxed space-y-1.5">
                        {logs.length > 0 ? logs.slice(0, visibleLogs).map((log, i) => (
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
                                    {['success', 'ok'].includes(log.status) ? '>> OK' : '!! ERR'}
                                </span>
                                <span className="text-white/80 flex-1 truncate">
                                    {log.action} <span className="text-primary/40">NODE_{log.nip.slice(-4)}</span>
                                </span>
                            </motion.div>
                        )) : (
                            <div className="h-full flex flex-col items-center justify-center opacity-30 py-20">
                                <RiTerminalBoxLine className="h-12 w-12 mb-4" />
                                <p className="uppercase tracking-[0.2em] text-[8px]">Awaiting_Telemetry_Data...</p>
                            </div>
                        )}
                        
                        {logs.length > visibleLogs && (
                            <button 
                                onClick={() => setVisibleLogs(v => v + 20)}
                                className="w-full py-4 mt-4 border-t border-white/5 text-primary/40 hover:text-primary transition-colors uppercase tracking-[0.4em] text-[8px] font-black"
                            >
                                Load_Next_Sequence (+{logs.length - visibleLogs})
                            </button>
                        )}
                    </div>
                </Card>
            </div>
        );
    }

    if (activeTab === 'kernel') {
        const isOnline = stats.uptime === 'ONLINE';
        return (
            <div className="space-y-8 animate-in fade-in slide-in-from-bottom-4 duration-500">
                {renderHeader('CORE.EXE', 'System Kernel Status', HiOutlineCpuChip, 'SYS_ADMIN_ACTIVE')}
                
                <div className="grid grid-cols-2 gap-4">
                    <Card className="glass-premium p-5 flex flex-col gap-3 relative overflow-hidden group border-primary/10">
                        <RiPulseLine className={cn("absolute -right-4 -bottom-4 h-20 w-20 opacity-10", isOnline ? "text-emerald-500" : "text-amber-500")} />
                        <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Runtime</p>
                        <div className="flex items-center gap-3">
                             <div className={cn("w-2.5 h-2.5 rounded-full", isOnline ? "bg-emerald-500 animate-pulse shadow-[0_0_10px_rgba(16,185,129,0.8)]" : "bg-amber-500")} />
                             <p className={cn("text-2xl font-black italic tracking-tighter leading-none", isOnline ? "text-emerald-500" : "text-amber-500")}>{stats.uptime}</p>
                        </div>
                    </Card>
                    <Card className="glass-premium p-5 flex flex-col gap-3 relative overflow-hidden border-primary/10">
                        <RiDatabase2Line className="absolute -right-4 -bottom-4 h-20 w-20 opacity-10 text-primary" />
                        <p className="text-[9px] font-black text-muted-foreground uppercase tracking-widest opacity-60">Database</p>
                        <p className="text-2xl font-black text-primary italic leading-none tracking-tighter">ESTABLISHED</p>
                    </Card>
                </div>

                <Card className="glass-premium p-6 space-y-8 border-primary/10">
                    <div className="flex justify-between items-center bg-white/5 p-4 rounded-2xl border border-white/5">
                        <div className="flex items-center gap-4">
                            <div className={cn("p-2.5 rounded-xl transition-colors", maintMode ? "bg-amber-500/20 text-amber-500" : "bg-white/5 text-muted-foreground")}>
                                <RiToggleLine className="h-6 w-6" />
                            </div>
                            <div className="space-y-0.5">
                                <p className="text-xs font-black text-white uppercase tracking-tight">Safe Mode</p>
                                <p className="text-[8px] text-muted-foreground uppercase tracking-widest opacity-50">Lock Global Absence Trigger</p>
                            </div>
                        </div>
                        <button 
                            onClick={() => {
                                setMaintMode(!maintMode);
                                toast.warning(`Safety Lock ${!maintMode ? 'ENGAGED' : 'RELEASED'}`);
                            }}
                            className={cn(
                                "w-12 h-6 rounded-full transition-all p-1 relative",
                                maintMode ? "bg-amber-500 shadow-[0_0_15px_rgba(245,158,11,0.3)]" : "bg-slate-800"
                            )}
                        >
                            <div className={cn(
                                "w-4 h-4 rounded-full bg-white transition-all shadow-md",
                                maintMode ? "translate-x-6" : "translate-x-0"
                            )} />
                        </button>
                    </div>

                    <div className="space-y-4">
                        <div className="flex justify-between items-end">
                            <p className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/60">Processor_Load</p>
                            <span className="text-sm font-black text-primary italic tracking-tighter">{stats.clusters} Active Tasks</span>
                        </div>
                        <div className="h-2 w-full bg-white/5 rounded-full overflow-hidden border border-white/5 p-0.5">
                            <motion.div 
                                initial={{ width: 0 }}
                                animate={{ width: `${Math.min(100, stats.clusters * 10)}%` }} 
                                className="h-full bg-gradient-to-r from-primary to-blue-400 rounded-full shadow-[0_0_15px_rgba(59,130,246,0.5)]" 
                            />
                        </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-4">
                        <Button className="h-9 font-black uppercase tracking-[0.2em] text-[9px] rounded-xl shadow-xl hover:scale-[1.02] active:scale-[0.98] transition-all bg-primary" onClick={triggerSync}>Restart Engine</Button>
                        <Button variant="secondary" className="h-9 font-black uppercase tracking-[0.2em] text-[9px] rounded-xl bg-white/5 border border-white/10 hover:bg-white/10" onClick={() => toast.success('Cache Flushed')}>Purge Cache</Button>
                    </div>
                </Card>

                <div className="p-6 rounded-[32px] bg-slate-900/60 border border-primary/10 font-mono text-[9px] leading-relaxed space-y-2 relative overflow-hidden">
                    <div className="absolute top-0 right-0 p-2 opacity-10">
                        <RiTerminalBoxLine className="h-16 w-16 text-primary" />
                    </div>
                    <div className="flex items-center gap-3 mb-4 border-b border-white/5 pb-3">
                        <div className="w-2 h-2 rounded-full bg-primary animate-pulse" />
                        <p className="font-bold text-white uppercase tracking-[0.3em]">Diagnostic_Stream</p>
                    </div>
                    <p className="text-emerald-500/70 animate-pulse">[{new Date().toISOString().slice(11,19)}] SYNC_LISTENER: Established</p>
                    <p className="text-emerald-500/70">[{new Date().toISOString().slice(11,19)}] AUTH_GATEWAY: Level_5_Authorized</p>
                    <p className="text-primary/70">[{new Date().toISOString().slice(11,19)}] PGQUEUER: {stats.clusters} workers_idled</p>
                    <p className="text-amber-500/70">[{new Date().toISOString().slice(11,19)}] KERNEL: Heartbeat_Relayed...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-10 animate-in fade-in slide-in-from-bottom-4 duration-500">
            {renderHeader('CORE.OPS', 'Intercontinental Authority', HiOutlineShieldCheck, 'ROOT_ADMIN_SECURED', HiOutlineGlobeAlt)}
            
            <div className="grid grid-cols-2 gap-4">
                <Card className="glass-premium p-6 space-y-4 relative overflow-hidden group border-primary/10">
                    <HiOutlineServerStack className="h-10 w-10 text-primary absolute -right-2 -bottom-2 opacity-5 group-hover:scale-110 transition-transform" />
                    <div className="space-y-1">
                        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/50">Active Matrix</p>
                        <p className="text-4xl font-black text-white tracking-tighter leading-none">{users.length}</p>
                    </div>
                    <Badge variant="outline" className="text-[8px] font-black tracking-[0.2em] h-5 px-2 border-emerald-500/20 text-emerald-500 bg-emerald-500/5">ONLINE</Badge>
                </Card>
                <Card className="glass-premium p-6 space-y-4 relative overflow-hidden group border-primary/10">
                    <HiOutlineShieldCheck className="h-10 w-10 text-emerald-500 absolute -right-2 -bottom-2 opacity-5 group-hover:scale-110 transition-transform" />
                    <div className="space-y-1">
                        <p className="text-[10px] font-black uppercase tracking-[0.2em] text-muted-foreground/50">Success Ops</p>
                        <p className="text-4xl font-black text-white tracking-tighter leading-none">{stats.total}</p>
                    </div>
                    <Badge variant="outline" className="text-[8px] font-black tracking-[0.2em] h-5 px-2 border-primary/20 text-primary bg-primary/5">VERIFIED</Badge>
                </Card>
            </div>

            <motion.div initial={{ opacity: 0, scale: 0.98 }} animate={{ opacity: 1, scale: 1 }} transition={{ delay: 0.1 }}>
                <Card className="glass-premium overflow-hidden border-primary/20 shadow-[0_0_30px_rgba(59,130,246,0.1)] rounded-[24px]">
                    <CardContent className="p-4 space-y-6">
                        <div className="flex justify-between items-center text-center">
                            <div className="flex-1 space-y-1">
                                <p className="text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground/40">Network</p>
                                <p className={cn("text-3xl font-black tracking-tighter italic leading-none drop-shadow-sm", stats.uptime === 'ONLINE' ? "text-white" : "text-amber-500")}>{stats.uptime}</p>
                            </div>
                            <div className="h-8 w-[1px] bg-white/10" />
                            <div className="flex-1 space-y-1">
                                <p className="text-[9px] font-black uppercase tracking-[0.2em] text-muted-foreground/40">Load</p>
                                <p className="text-3xl font-black text-primary tracking-tighter leading-none drop-shadow-md text-glow">{stats.clusters}</p>
                            </div>
                        </div>
                        
                        <Button 
                            onClick={triggerSync} 
                            className="w-full h-10 rounded-xl font-black uppercase tracking-[0.2em] text-[10px] shadow-xl shadow-primary/30 hover:shadow-primary/50 transition-all active:scale-[0.98] relative overflow-hidden group"
                        >
                            <div className="absolute inset-0 bg-gradient-to-r from-primary to-blue-400 group-hover:opacity-90 transition-opacity" />
                            <div className="relative flex items-center justify-center">
                                <RiRefreshLine className="mr-3 h-4 w-4 animate-spin-slow" /> 
                                Global Sync
                            </div>
                        </Button>
                    </CardContent>
                </Card>
            </motion.div>

            <Card className="glass-premium border-primary/10 p-4 shadow-xl rounded-[24px]">
                <ActivityHeatmap data={stats.activity} />
            </Card>
        </div>
    );
};
