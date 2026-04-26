import React, { useEffect, useState } from 'react';
import { Toaster, toast } from 'sonner';
import { motion, AnimatePresence } from 'motion/react';
import { supabase } from '@/lib/supabase';
import { AuthLoading } from '@/components/layout/AuthLoading';
import { AuthError } from '@/components/layout/AuthError';
import { BottomNav } from '@/components/layout/BottomNav';
import { UserDashboard } from '@/components/dashboard/UserDashboard';
import { AdminDashboard } from '@/components/dashboard/AdminDashboard';
import { User } from '@/types/user';
import { AttendanceLog, SystemStats, TelegramWebApp } from '@/types/system';

const tg = (window as unknown as { Telegram?: { WebApp: TelegramWebApp } }).Telegram?.WebApp;

const pageVariants = {
    initial: { opacity: 0, scale: 0.98 },
    animate: { opacity: 1, scale: 1 },
    exit: { opacity: 0, scale: 0.98 }
};

export default function App() {
    const [userProfile, setUserProfile] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [activeTab, setActiveTab] = useState<string>('');
    const [attendanceLog, setAttendanceLog] = useState<AttendanceLog[]>([]);
    const [stats, setStats] = useState<SystemStats>({ 
        total: 0, 
        uptime: 'ONLINE', 
        security: 'ENCRYPTED', 
        clusters: 0,
        activity: new Array(30).fill(0)
    });
    const [allUsers, setAllUsers] = useState<User[]>([]);
    const [userLocation, setUserLocation] = useState<{ lat: number, lng: number } | null>(null);

    const changeTab = (tab: string) => {
        if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('light');
        setActiveTab(tab);
    };

    const fetchLocation = () => {
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition((pos) => {
                setUserLocation({ lat: pos.coords.latitude, lng: pos.coords.longitude });
            });
        }
    };

    useEffect(() => {
        let cleanup: (() => void) | undefined;
        initAuth().then(res => {
            if (typeof res === 'function') cleanup = res;
        });
        return () => {
            if (cleanup) cleanup();
        };
    }, []);

    async function initAuth() {
        try {
            if (!tg) {
                setError('Akses Terbatas: Sistem Enterprise hanya dapat dibuka melalui Telegram Mini App.');
                setLoading(false);
                return;
            }

            tg.expand();
            tg.ready();
            const telegramUser = tg.initDataUnsafe?.user;

            if (!telegramUser) {
                setError('Mohon buka aplikasi ini melalui Telegram.');
                setLoading(false);
                return;
            }

            const { data } = await supabase
                .from('users')
                .select('*, upts(nama_upt)')
                .eq('telegram_id', telegramUser.id)
                .single();

            setUserProfile(data);
            setActiveTab(data.role === 'admin' ? 'stats' : 'nexus');
            fetchLocation();

            // Fetch Logs (Admin sees ALL, User sees Self)
            const logQuery = supabase
                .from('audit_logs')
                .select('*')
                .order('timestamp', { ascending: false })
                .limit(100);
            
            if (data.role !== 'admin') {
                logQuery.eq('nip', data.nip);
            }

            const { data: logs } = await logQuery;
            
            // Success Ops Count (Admin sees Total System Success, User sees Self)
            const successCountQuery = supabase
                .from('audit_logs')
                .select('*', { count: 'exact', head: true })
                .in('status', ['success', 'ok']);
            
            if (data.role !== 'admin') {
                successCountQuery.eq('nip', data.nip);
            }
            
            const { count } = await successCountQuery;

            // Generate Heatmap Data (Last 364 Days / 52 Weeks)
            const totalDays = 52 * 7;
            const oneYearAgo = new Date();
            oneYearAgo.setDate(oneYearAgo.getDate() - totalDays);
            
            let activityQuery = supabase
                .from('audit_logs')
                .select('timestamp')
                .gte('timestamp', oneYearAgo.toISOString());
            
            // Only filter by NIP if NOT admin (Admin sees system-wide pulses)
            if (data.role !== 'admin') {
                activityQuery = activityQuery.eq('nip', data.nip);
            }
            
            const { data: activity, error: activityError } = await activityQuery;
            if (activityError) console.error('ACTIVITY_QUERY_ERR:', activityError);
            
            const activityMap = new Array(totalDays).fill(0);
            const now = new Date();
            now.setHours(0, 0, 0, 0);

            let logsCount = 0;
            activity?.forEach(log => {
                const logDate = new Date(log.timestamp);
                logDate.setHours(0, 0, 0, 0);
                const dayDiff = Math.round((now.getTime() - logDate.getTime()) / (1000 * 3600 * 24));
                if (dayDiff >= 0 && dayDiff < totalDays) {
                    activityMap[totalDays - 1 - dayDiff] += 1;
                    logsCount++;
                }
            });

            setAttendanceLog(logs || []);
            
            setStats(s => ({ 
                ...s, 
                total: count || 0, 
                activity: activityMap 
            }));

            // --- REALTIME SUBSCRIPTION (Isolated & Hardened) ---
            let channel: any;
            try {
                // Use unique channel name to avoid clashing on re-renders
                channel = supabase
                    .channel(`rt_audit_${Date.now()}`)
                    .on('postgres_changes', { 
                        event: 'INSERT', 
                        schema: 'public', 
                        table: 'audit_logs' 
                    }, (payload) => {
                        const newLog = payload.new as AttendanceLog;
                        if (data.role === 'admin' || newLog.nip === data.nip) {
                            setAttendanceLog(prev => [newLog, ...prev].slice(0, 100));
                            setStats(s => {
                                const newActivity = [...s.activity];
                                if (newActivity.length > 0) {
                                    newActivity[newActivity.length - 1] += 1;
                                }
                                return { ...s, activity: newActivity, total: s.total + 1 };
                            });
                            if (tg?.HapticFeedback) tg.HapticFeedback.impactOccurred('medium');
                            toast.info(`SYSTEM_SIGNAL: ${newLog.action}`, { icon: '📡' });
                        }
                    })
                    .subscribe();
            } catch (rtErr) {
                console.error('Realtime Sync Error:', rtErr);
                // Don't crash the whole app if realtime fails
            }

            // Poll Kernel Data (FastAPI /healthz)
            const fetchKernel = async () => {
                try {
                    const apiBase = import.meta.env.VITE_API_URL || '';
                    const res = await fetch(`${apiBase}/healthz`);
                    const health = await res.json();
                    setStats(s => ({
                        ...s,
                        uptime: health.status === 'ok' ? 'ONLINE' : 'DEGRADED',
                        clusters: health.scheduler_jobs || s.clusters
                    }));
                } catch {
                    // Fail silently
                }
            };
            
            fetchKernel();
            const interval = setInterval(fetchKernel, 30000); // Every 30s
            
            if (data.role === 'admin') {
                const { data: users } = await supabase
                    .from('users')
                    .select('*, upts(nama_upt)')
                    .limit(100);
                
                const { count: totalUsers } = await supabase
                    .from('users')
                    .select('*', { count: 'exact', head: true });
                
                setAllUsers(users || []);
                setStats(prev => ({ ...prev, clusters: totalUsers || 0 }));
            }
            
            setLoading(false);
            
            if (data?.nama) {
                toast.success(`Selamat datang, ${data.nama}`);
            }

            return () => {
                supabase.removeChannel(channel);
                clearInterval(interval);
            };
        } catch (err) {
            console.error(err);
            setError('System Error. Please contact support.');
            setLoading(false);
        }
    }

    if (loading) return <AuthLoading />;

    return (
        <div className="h-full bg-background flex flex-col relative overflow-hidden">
            <Toaster position="top-center" theme="dark" richColors closeButton />
            
            <div className="flex-1 overflow-y-auto no-scrollbar">
                <AnimatePresence mode="wait">
                    <motion.main 
                        key={activeTab} // Trigger transition on tab change
                        variants={pageVariants}
                        initial="initial"
                        animate="animate"
                        exit="exit"
                        transition={{ duration: 0.3 }}
                        className="max-w-[480px] mx-auto w-full min-h-full px-1 flex flex-col justify-start pt-6 pb-6"
                    >
                        {error ? (
                            <AuthError error={error} />
                        ) : userProfile?.role === 'admin' ? (
                            <AdminDashboard 
                                _user={userProfile} 
                                activeTab={activeTab} 
                                users={allUsers}
                                stats={stats}
                                logs={attendanceLog}
                            />
                        ) : (
                            <UserDashboard 
                                user={userProfile!} 
                                activeTab={activeTab} 
                                logs={attendanceLog}
                                stats={stats}
                                userLocation={userLocation}
                            />
                        )}
                        
                        {/* Finely tuned space for fixed bottom nav */}
                        <div className="h-20 flex-shrink-0" />
                    </motion.main>
                </AnimatePresence>
            </div>
            
            <BottomNav 
                isAdmin={userProfile?.role === 'admin'} 
                activeTab={activeTab}
                onTabChange={changeTab}
            />
        </div>
    );
}
