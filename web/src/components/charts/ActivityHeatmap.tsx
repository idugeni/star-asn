import React from 'react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';

// Enterprise Activity Heatmap (Real Data Driven)
interface ActivityHeatmapProps {
    data?: number[]; // Expecting array of 30 values for last month
}

export const ActivityHeatmap = ({ data }: ActivityHeatmapProps) => {
    // If no data, show a zeroed out map instead of random mocks
    const heatmapData = data || new Array(30).fill(0);
    
    const getColor = (level: number) => {
        if (level === 0) return 'bg-white/[0.02] border-white/[0.05]';
        if (level === 1) return 'bg-primary/20 border-primary/30';
        if (level > 1) return 'bg-primary border-primary/50 shadow-[0_0_8px_rgba(59,130,246,0.4)]';
        return 'bg-white/[0.02]';
    };

    return (
        <div className="space-y-4 p-1">
            <div className="flex items-center justify-between">
                <div className="space-y-0.5">
                    <h4 className="text-[9px] font-black uppercase tracking-[0.2em] text-slate-400">Node Activity</h4>
                    <p className="text-[8px] text-slate-600 font-medium italic">Trailing 30-day telemetry</p>
                </div>
                <div className="flex items-center gap-1.5 text-[7px] text-slate-500 font-bold uppercase tracking-wider">
                    <span>Low</span>
                    <div className="flex gap-0.5">
                        {[0, 1, 2].map(l => (
                            <div key={l} className={cn("w-2 h-2 rounded-[1px] border", getColor(l))} />
                        ))}
                    </div>
                    <span>High</span>
                </div>
            </div>
            
            <div className="flex gap-[4px] justify-center pt-2">
                {heatmapData.map((level, i) => (
                    <motion.div
                        key={i}
                        initial={{ scale: 0.8, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ delay: i * 0.01 }}
                        className={cn(
                            "flex-1 h-6 rounded-[2px] border transition-all duration-300 relative group",
                            getColor(level)
                        )}
                    >
                        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-1.5 py-0.5 bg-slate-900 border border-white/10 rounded text-[6px] font-black text-white opacity-0 group-hover:opacity-100 pointer-events-none transition-opacity whitespace-nowrap z-50 uppercase">
                            {level} Presence • T-{29 - i}D
                        </div>
                    </motion.div>
                ))}
            </div>
            
            <div className="flex justify-between text-[6px] font-black text-slate-700 uppercase tracking-[0.4em] px-1 pt-1 border-t border-white/[0.03]">
                <span>T-30 Days</span>
                <span>Today</span>
            </div>
        </div>
    );
};
