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
        <nav className="fixed bottom-8 left-0 right-0 z-50 flex justify-center px-4">
            <div className="glass shadow-[0_20px_50px_rgba(0,0,0,0.5)] border-white/5 flex justify-around items-center py-4 px-8 rounded-[32px] w-full max-w-sm relative">
                <div className="absolute inset-0 bg-primary/5 blur-2xl rounded-full -z-10" />
                {items.map((item) => {
                    const isActive = activeTab === item.id;
                    return (
                        <motion.button 
                            key={item.id} 
                            onClick={() => onTabChange(item.id)}
                            whileHover={{ y: -5 }}
                            whileTap={{ scale: 0.9, y: 0 }}
                            className={cn(
                                "flex flex-col items-center gap-1.5 relative group outline-none cursor-pointer",
                                isActive ? "text-primary" : "text-slate-600 hover:text-slate-400"
                            )}
                        >
                            <item.icon className={cn(
                                "h-7 w-7 transition-all duration-300", 
                                isActive ? "drop-shadow-[0_0_8px_rgba(59,130,246,0.5)]" : "group-hover:opacity-100"
                            )} />
                            <span className={cn(
                                "text-[8px] font-black uppercase tracking-[0.2em] transition-all",
                                isActive ? "opacity-100" : "opacity-40 group-hover:opacity-100"
                            )}>
                                {item.label}
                            </span>
                            {isActive && (
                                <motion.div 
                                    layoutId="nav-dot"
                                    className="absolute -bottom-1.5 w-1 h-1 bg-primary rounded-full shadow-[0_0_8px_rgba(59,130,246,0.8)]"
                                />
                            )}
                        </motion.button>
                    );
                })}
            </div>
        </nav>
    );
};
