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
        const id = toast.loading('Initiating Mass Node Sync...');
        const apiBase = import.meta.env.VITE_API_URL || '';
        try {
            await fetch(`${apiBase}/internal/scheduler/sync`, { method: 'POST' });
            toast.success('Sync Complete: All Nodes Synchronized.', { id });
        } catch (err) {
            toast.error('Sync Refused: Hardware Latency.', { id });
        }
    };

    const renderHeader = (title: string, sub: string, BadgeIcon: React.ElementType, badgeText: string, ActionIcon?: React.ElementType, action?: () => void) => (
        <header className="flex justify-between items-start">
            <div className="space-y-2">
                <Badge variant="destructive" className="gap-1.5 bg-destructive/10 text-destructive border-transparent px-2 py-0.5 uppercase tracking-widest font-black text-[7px]">
                    <BadgeIcon className="h-2.5 w-2.5" /> {badgeText}
                </Badge>
                <div className="space-y-0.5">
                    <h1 className="text-2xl font-black tracking-tight text-white italic uppercase">
                        {title.split('.')[0]}.<span className="text-primary">{title.split('.')[1]}</span>
                    </h1>
                    <p className="text-[7px] font-black uppercase tracking-[0.3em] text-muted-foreground italic opacity-50">
                        {sub}
                    </p>
                </div>
            </div>
            {ActionIcon && (
                <Button variant="secondary" size="icon" onClick={action} className="w-10 h-10 rounded-xl border border-white/5">
                    <ActionIcon className="h-4 w-4" />
                </Button>
            )}
        </header>
    );

    if (activeTab === 'nodes') {
        return (
            <div className="space-y-6">
                {renderHeader('PERSONNEL.MANIFEST', 'Global Node Directory', HiOutlineUsers, 'ACCESS_LEVEL_TOP', RiDownloadCloud2Line)}
                
                <div className="grid gap-3">
                    <div className="relative group">
                        <RiSearchLine className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-700" />
                        <Input 
                            value={searchQuery}
                            onChange={(e) => setSearchQuery(e.target.value)}
                            placeholder="SEARCH NIP/NAME..." 
                            className="h-12 pl-12 rounded-xl bg-card/60 border-border/50 font-black tracking-widest text-[9px] focus:bg-card/80 transition-all"
                        />
                    </div>
                    <div className="flex gap-2 p-1 bg-white/5 rounded-xl">
                        {['all', 'admin', 'user'].map((r) => (
                            <button
                                key={r}
                                onClick={() => setFilterRole(r as any)}
                                className={cn(
                                    "flex-1 py-1.5 rounded-lg text-[8px] font-black uppercase transition-all tracking-widest",
                                    filterRole === r ? "bg-primary text-white shadow-lg" : "text-slate-500 hover:bg-white/5"
                                )}
                            >
                                {r}
                            </button>
                        ))}
                    </div>
                </div>

                {selectedUser && (
                    <Card className="bg-primary/5 border-primary/20 overflow-hidden">
                        <CardContent className="p-4 space-y-4">
                            <div className="flex justify-between items-start gap-3">
                                <div className="space-y-1">
                                    <p className="text-[7px] font-black uppercase tracking-[0.3em] text-primary/70">Selected Personnel</p>
                                    <h3 className="text-base font-black text-white uppercase leading-tight">{selectedUser.nama}</h3>
                                    <p className="text-[9px] font-mono font-bold text-primary tracking-tight">NIP {selectedUser.nip}</p>
                                </div>
                                <Badge className={cn("text-[6px] font-black border-none px-2 py-0.5", selectedUser.role === 'admin' ? "bg-primary text-white" : "bg-emerald-500 text-white")}>
                                    {selectedUser.role.toUpperCase()}
                                </Badge>
                            </div>
                            <div className="grid grid-cols-2 gap-3 border-t border-white/5 pt-3">
                                <div className="space-y-1">
                                    <p className="text-[7px] font-black uppercase opacity-40">Work Node</p>
                                    <p className="text-[10px] font-bold text-white uppercase leading-tight">{selectedUser.upts?.nama_upt || 'Regional Standalone Node'}</p>
                                </div>
                                <div className="space-y-1 text-right">
                                    <p className="text-[7px] font-black uppercase opacity-40">Schedule</p>
                                    <p className="text-[10px] font-mono font-black text-amber-500">{selectedUser.cron_in} - {selectedUser.cron_out}</p>
                                </div>
                            </div>
                        </CardContent>
                    </Card>
                )}

                <div className="grid gap-4">
                    {displayedUsers.map((person, i) => (
                        <motion.button
                            key={person.nip}
                            type="button"
                            initial={{ opacity: 0, y: 10 }}
                            animate={{ opacity: 1, y: 0 }}
                            transition={{ delay: i * 0.03 }}
                            onClick={() => setSelectedUserNip(person.nip)}
                            aria-pressed={selectedUser?.nip === person.nip}
                            className="block w-full text-left"
                        >
                            <Card className={cn(
                                "bg-card/40 border-border/50 overflow-hidden group transition-all cursor-pointer",
                                selectedUser?.nip === person.nip
                                    ? "border-primary/60 bg-primary/5 shadow-lg shadow-primary/10"
                                    : "hover:bg-accent/5"
                            )}>
                                <CardContent className="p-4 space-y-4">
                                    <div className="flex flex-col gap-1">
                                        <div className="flex justify-between items-center">
                                            <Badge className={cn("text-[6px] font-black border-none px-2 py-0.5", person.role === 'admin' ? "bg-primary text-white" : "bg-emerald-500 text-white")}>
                                                {person.role.toUpperCase()}
                                            </Badge>
                                            <div className="flex items-center gap-2">
                                                {selectedUser?.nip === person.nip && (
                                                    <Badge variant="outline" className="h-5 border-primary/30 bg-primary/10 px-2 text-[6px] font-black uppercase tracking-widest text-primary">
                                                        Selected
                                                    </Badge>
                                                )}
                                                <p className="text-[7px] font-mono text-muted-foreground/50 uppercase tracking-tighter">NODE_{person.nip.slice(-4)}</p>
                                            </div>
                                        </div>
                                        <h3 className="text-sm font-black text-white uppercase tracking-tight leading-tight">{person.nama}</h3>
                                        <p className="text-[9px] font-mono font-bold text-primary mt-0.5 tracking-tight">NIP {person.nip}</p>
                                    </div>

                                    <div className="grid grid-cols-2 gap-4 pt-3 border-t border-white/5">
                                        <div className="col-span-2">
                                            <p className="text-[7px] font-black uppercase opacity-40 mb-1 flex items-center gap-1.5">
                                                <HiOutlineGlobeAlt className="h-2.5 w-2.5" /> Work Node (UPT)
                                            </p>
                                            <p className="text-[10px] font-bold text-white uppercase break-words leading-tight">{person.upts?.nama_upt || 'Regional Standalone Node'}</p>
                                        </div>
                                        <div className="flex flex-col gap-1">
                                            <p className="text-[7px] font-black uppercase opacity-40 flex items-center gap-1.5">
                                                <HiOutlineClock className="h-2.5 w-2.5" /> Sched
                                            </p>
                                            <p className="text-[10px] font-mono font-black text-amber-500">{person.cron_in} - {person.cron_out}</p>
                                        </div>
                                        <div className="flex flex-col gap-1 text-right items-end">
                                            <p className="text-[7px] font-black uppercase opacity-40 flex items-center gap-1.5">
                                                Status
                                            </p>
                                            <Badge variant="outline" className="text-[8px] h-5 border-emerald-500/20 text-emerald-500 bg-emerald-500/5 px-2">ACTIVE</Badge>
                                        </div>
                                    </div>
                                </CardContent>
                            </Card>
                        </motion.button>
                    ))}
                    {filteredUsers.length > visibleNodes && (
                        <Button variant="ghost" onClick={() => setVisibleNodes(v => v + 10)} className="w-full text-[8px] font-black uppercase tracking-widest text-muted-foreground py-6">
                            Load {filteredUsers.length - visibleNodes} More Personnel
                        </Button>
                    )}
                </div>
            </div>
        );
    }

    if (activeTab === 'logs') {
        const hasLogs = logs.length > 0;
        return (
            <div className="space-y-6">
                {renderHeader('SYS.LOGS', 'Infrastructure Event Feed', RiHistoryLine, 'READ_ONLY', RiRefreshLine, () => window.location.reload())}
                <div className="grid gap-2">
                    {hasLogs ? displayedLogs.map((log, i) => (
                        <Card key={i} className="bg-card/40 border-border/50 p-4 flex justify-between items-center group transition-colors hover:bg-accent/5">
                            <div className="space-y-0.5">
                                <p className="text-[10px] font-black text-white uppercase">{log.action}</p>
                                <p className="text-[8px] font-mono text-muted-foreground uppercase opacity-50">{new Date(log.timestamp).toLocaleTimeString()}</p>
                            </div>
                            <div className="text-right flex flex-col items-end gap-1">
                                <Badge className={cn("text-[7px] font-black border-none px-2 py-0.5", log.status === 'SUCCESS' ? 'bg-emerald-500/10 text-emerald-500' : 'bg-destructive/10 text-destructive')}>
                                    {log.status}
                                </Badge>
                                <p className="text-[6px] font-mono text-muted-foreground uppercase opacity-20">{log.nip}</p>
                            </div>
                        </Card>
                    )) : (
                        <div className="text-center py-20 px-6 border-2 border-dashed border-white/5 rounded-3xl">
                            <RiTerminalBoxLine className="h-10 w-10 text-slate-800 mx-auto mb-4" />
                            <p className="text-[10px] font-black text-slate-700 uppercase tracking-widest">No Logs Detected in Matrix</p>
                            <p className="text-[8px] text-slate-800 mt-2 uppercase font-mono">Ensure RLS Patch 'fix_admin_rls.py' is applied via SQL Editor.</p>
                        </div>
                    )}
                </div>
                {logs.length > visibleLogs && (
                    <Button variant="ghost" onClick={() => setVisibleLogs(v => v + 10)} className="w-full h-10 text-[8px] font-black uppercase tracking-widest text-muted-foreground">
                        Reveal Older Infrastructure Logs
                    </Button>
                )}
            </div>
        );
    }

    if (activeTab === 'kernel') {
        const isOnline = stats.uptime === 'ONLINE';
        return (
            <div className="space-y-6">
                {renderHeader('CORE.OS', 'System Kernel Parameters', HiOutlineCpuChip, 'ROOT_ADMIN')}
                
                <div className="grid grid-cols-2 gap-3">
                    <Card className="bg-card/40 border-border/50 p-4 flex flex-col gap-2 relative overflow-hidden group">
                        <RiPulseLine className={cn("absolute -right-2 -bottom-2 h-12 w-12 opacity-5", isOnline ? "text-emerald-500" : "text-amber-500")} />
                        <p className="text-[7px] font-black text-muted-foreground uppercase">Runtime Status</p>
                        <div className="flex items-center gap-2">
                             <div className={cn("w-2 h-2 rounded-full", isOnline ? "bg-emerald-500 animate-pulse" : "bg-amber-500")} />
                             <p className={cn("text-lg font-black italic", isOnline ? "text-emerald-500" : "text-amber-500")}>{stats.uptime}</p>
                        </div>
                    </Card>
                    <Card className="bg-card/40 border-border/50 p-4 flex flex-col gap-2 relative overflow-hidden">
                        <RiDatabase2Line className="absolute -right-2 -bottom-2 h-12 w-12 opacity-5 text-primary" />
                        <p className="text-[7px] font-black text-muted-foreground uppercase">DB Pool Status</p>
                        <p className="text-lg font-black text-primary italic leading-none">6543/Active</p>
                    </Card>
                </div>

                <Card className="bg-card/40 border-border/50 p-5 space-y-6 relative overflow-hidden">
                    <div className="flex justify-between items-center bg-white/5 p-3 rounded-xl">
                        <div className="flex items-center gap-3">
                            <RiToggleLine className={cn("h-5 w-5", maintMode ? "text-amber-500" : "text-slate-600")} />
                            <div className="space-y-0.5">
                                <p className="text-[9px] font-black text-white uppercase">Maintenance Mode</p>
                                <p className="text-[7px] text-muted-foreground uppercase">Lock absence for all nodes</p>
                            </div>
                        </div>
                        <button 
                            onClick={() => {
                                setMaintMode(!maintMode);
                                toast.warning(`Maintenance Mode ${!maintMode ? 'ARMED' : 'DISARMED'}`);
                            }}
                            className={cn(
                                "w-10 h-5 rounded-full transition-colors relative",
                                maintMode ? "bg-amber-500" : "bg-slate-800"
                            )}
                        >
                            <div className={cn(
                                "absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all",
                                maintMode ? "right-0.5" : "left-0.5"
                            )} />
                        </button>
                    </div>

                    <div className="space-y-4">
                        <div className="flex justify-between items-center text-[8px] font-black uppercase">
                            <span className="text-muted-foreground">Global_Job_Load</span>
                            <span className="text-primary italic">{stats.clusters} Task(s)</span>
                        </div>
                        <div className="h-1.5 w-full bg-white/5 rounded-full overflow-hidden">
                            <motion.div animate={{ width: `${Math.min(100, stats.clusters * 10)}%` }} className="h-full bg-primary" />
                        </div>
                    </div>
                    
                    <div className="grid grid-cols-2 gap-3">
                        <Button className="h-12 font-black uppercase tracking-widest text-[8px] rounded-xl shadow-lg" onClick={triggerSync}>Restart Engine</Button>
                        <Button variant="secondary" className="h-12 font-black uppercase tracking-widest text-[8px] rounded-xl border border-white/5" onClick={() => toast.success('Cache Flushed')}>Flush Cache</Button>
                    </div>
                </Card>

                <div className="p-4 border border-white/5 rounded-2xl bg-slate-900/40 font-mono text-[8.5px] leading-relaxed space-y-1">
                    <div className="flex items-center gap-2 mb-2 border-b border-white/5 pb-2">
                        <RiTerminalBoxLine className="h-4 w-4 text-primary" />
                        <p className="font-bold text-white uppercase tracking-widest">Diagnostic_Trace</p>
                    </div>
                    <p className="text-emerald-500/60 transition-opacity">[{new Date().toISOString().slice(11,19)}] SYNC_LISTENER: Connected</p>
                    <p className="text-emerald-500/60">[{new Date().toISOString().slice(11,19)}] AUTH_GATEWAY: Level 4 Active</p>
                    <p className="text-primary/60">[{new Date().toISOString().slice(11,19)}] PGQUEUER: {stats.clusters} workers prioritized</p>
                    <p className="text-amber-500/60 animate-pulse">[{new Date().toISOString().slice(11,19)}] KERNEL: Heartbeat Sent...</p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-6">
            {renderHeader('CORE.OPS', 'Intercontinental Network Authority', HiOutlineShieldCheck, 'ROOT@STAR_ASN', HiOutlineGlobeAlt)}
            <div className="grid grid-cols-2 gap-3">
                <Card className="bg-card/40 border-border/50 p-4 space-y-3 relative overflow-hidden group">
                    <HiOutlineServerStack className="h-6 w-6 text-primary absolute -right-1 -bottom-1 opacity-10" />
                    <p className="text-[8px] font-black uppercase tracking-wider text-muted-foreground/60">Active Matrix</p>
                    <p className="text-2xl font-black text-white tracking-tighter leading-none">{users.length}</p>
                    <Badge variant="secondary" className="text-[6px] tracking-widest italic h-4 px-1.5 border-border/30">ONLINE</Badge>
                </Card>
                <Card className="bg-card/40 border-border/50 p-4 space-y-3 relative overflow-hidden group">
                    <HiOutlineShieldCheck className="h-6 w-6 text-emerald-500 absolute -right-1 -bottom-1 opacity-10" />
                    <p className="text-[8px] font-black uppercase tracking-wider text-muted-foreground/60">Success Ops</p>
                    <p className="text-2xl font-black text-white tracking-tighter leading-none">{stats.total}</p>
                    <Badge variant="secondary" className="text-[6px] tracking-widest italic h-4 px-1.5 border-border/30">VERIFIED</Badge>
                </Card>
            </div>

            <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
                <Card className="glass overflow-hidden border-primary/10 shadow-premium">
                    <CardContent className="p-6 space-y-8">
                        <div className="flex justify-between items-center border-b border-white/5 pb-6 text-center">
                            <div className="flex-1 space-y-0.5">
                                <p className="text-[8px] font-black uppercase tracking-[0.2em] text-muted-foreground/60">Network</p>
                                <p className={cn("text-3xl font-black tracking-tighter italic leading-none", stats.uptime === 'ONLINE' ? "text-white" : "text-amber-500")}>{stats.uptime}</p>
                            </div>
                            <div className="h-8 w-[1px] bg-border/20" />
                            <div className="flex-1 space-y-0.5">
                                <p className="text-[8px] font-black uppercase tracking-[0.2em] text-muted-foreground/60">Tasks</p>
                                <p className="text-3xl font-black text-primary tracking-tighter leading-none">{stats.clusters}</p>
                            </div>
                        </div>
                        <Button onClick={triggerSync} className="w-full h-14 font-black uppercase tracking-[0.2em] text-[10px] rounded-xl group">
                            <RiRefreshLine className="mr-2 h-4 w-4 group-active:rotate-180 transition-transform" /> Global Sync
                        </Button>
                    </CardContent>
                </Card>
            </motion.div>
        </div>
    );
};
