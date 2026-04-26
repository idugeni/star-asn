import React from 'react';
import { motion } from 'motion/react';
import { HiOutlineChartBar, HiOutlineUsers, HiOutlineCog6Tooth, HiOutlineShieldCheck, HiOutlineCpuChip } from "react-icons/hi2";
import { RiHistoryLine } from "react-icons/ri";
import { cn } from '@/lib/utils';

interface BottomNavProps {
    isAdmin: boolean;
    activeTab: string;
    onTabChange: (tab: string) => void;
}

export const BottomNav = ({ isAdmin, activeTab, onTabChange }: BottomNavProps) => {
    const items = isAdmin 
        ? [
            { id: 'stats', icon: HiOutlineChartBar, label: 'Stats' },
            { id: 'nodes', icon: HiOutlineUsers, label: 'Nodes' },
            { id: 'logs', icon: RiHistoryLine, label: 'Logs' },
            { id: 'kernel', icon: HiOutlineCpuChip, label: 'Kernel' }
          ]
        : [
            { id: 'nexus', icon: HiOutlineShieldCheck, label: 'Nexus' },
            { id: 'records', icon: RiHistoryLine, label: 'Records' },
            { id: 'config', icon: HiOutlineCog6Tooth, label: 'Config' }
          ];

    return (
        <nav className="fixed bottom-6 left-0 right-0 z-50 flex justify-center px-8">
            <div className="glass-premium shadow-[0_15px_40px_rgba(0,0,0,0.5)] border-white/10 flex justify-around items-center py-2.5 px-6 rounded-[28px] w-full max-w-[320px] relative overflow-hidden group">
                <div className="absolute inset-0 bg-primary/5 blur-[30px] rounded-full -z-10 group-hover:bg-primary/10 transition-colors" />
                {items.map((item) => {
                    const isActive = activeTab === item.id;
                    return (
                        <motion.button 
                            key={item.id} 
                            onClick={() => onTabChange(item.id)}
                            whileHover={{ y: -3, scale: 1.1 }}
                            whileTap={{ scale: 0.95, y: 0 }}
                            className={cn(
                                "flex flex-col items-center gap-1 relative group outline-none cursor-pointer min-w-[45px]",
                                isActive ? "text-primary" : "text-slate-500 hover:text-slate-300"
                            )}
                        >
                            <item.icon className={cn(
                                "h-4.5 w-4.5 transition-all duration-300", 
                                isActive ? "drop-shadow-[0_0_10px_rgba(59,130,246,0.8)] scale-110" : "group-hover:opacity-100"
                            )} />
                            <span className={cn(
                                "text-[6px] font-black uppercase tracking-[0.2em] transition-all",
                                isActive ? "opacity-100 text-glow" : "opacity-30 group-hover:opacity-100"
                            )}>
                                {item.label}
                            </span>
                            {isActive && (
                                <motion.div 
                                    layoutId="nav-dot"
                                    className="absolute -bottom-1.5 w-1 h-1 bg-primary rounded-full shadow-[0_0_10px_rgba(59,130,246,1)]"
                                />
                            )}
                        </motion.button>
                    );
                })}
            </div>
        </nav>
    );
};
