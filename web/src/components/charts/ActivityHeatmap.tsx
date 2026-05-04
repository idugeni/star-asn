import React, { useMemo } from 'react';
import { motion } from 'motion/react';
import { cn } from '@/lib/utils';

interface ActivityHeatmapProps {
    data?: number[]; // We'll adapt this to a grid
}

export const ActivityHeatmap = ({ data }: ActivityHeatmapProps) => {
    const totalDays = 52 * 7;
    const scrollRef = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        if (scrollRef.current) {
            scrollRef.current.scrollLeft = scrollRef.current.scrollWidth;
        }
    }, [data]);

    const fullYearData = useMemo(() => {
        if (data && data.length === totalDays) return data;
        const base = new Array(totalDays).fill(0);
        if (data && data.length > 0) {
            for (let i = 0; i < data.length; i++) {
                const targetIdx = totalDays - data.length + i;
                if (targetIdx >= 0) base[targetIdx] = data[i];
            }
        }
        return base;
    }, [data, totalDays]);

    const getColor = (level: number) => {
        if (!level || level === 0) return 'bg-[#161b22]';
        if (level === 1) return 'bg-[#0e4429]';
        if (level === 2) return 'bg-[#006d32]';
        if (level === 3) return 'bg-[#26a641]';
        return 'bg-[#39d353] shadow-[0_0_8px_rgba(57,211,83,0.4)]';
    };

    // Robust Month Header Alignment
    const monthHeaders = useMemo(() => {
        const headers: { label: string; weekIndex: number }[] = [];
        const now = new Date();
        
        for (let i = 51; i >= 0; i--) {
            const date = new Date(now.getFullYear(), now.getMonth(), now.getDate() - (i * 7));
            const monthLabel = date.toLocaleString('default', { month: 'short' });
            const prevHeader = headers[headers.length - 1];
            if (headers.length === 0 || (prevHeader && prevHeader.label !== monthLabel)) {
                headers.push({ label: monthLabel, weekIndex: 51 - i });
            }
        }
        return headers;
    }, []);

    return (
        <div className="space-y-4">
            <div className="flex items-center justify-between px-1">
                <div className="space-y-0.5">
                    <h4 className="text-[9px] font-black uppercase tracking-[0.2em] text-white/80">Node Presence Manifest</h4>
                    <p className="text-[7px] text-muted-foreground/40 font-black uppercase tracking-widest italic">Full-cycle activity monitoring</p>
                </div>
                <div className="flex items-center gap-2">
                    <div className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="text-[6px] font-black text-emerald-500 uppercase tracking-widest">Live_Feed</span>
                </div>
            </div>

            <div className="relative">
                <div 
                    ref={scrollRef}
                    className="overflow-x-auto no-scrollbar scroll-smooth"
                >
                    <div className="min-w-max pb-2 px-1">
                        {/* Aligned Month Headers */}
                        <div className="relative h-4 ml-8 mb-1">
                            {monthHeaders.map((header, i) => (
                                <span 
                                    key={i} 
                                    className="absolute text-[6px] font-black text-muted-foreground/30 uppercase tracking-widest"
                                    style={{ left: `${header.weekIndex * 11}px` }}
                                >
                                    {header.label}
                                </span>
                            ))}
                        </div>

                        <div className="flex gap-[6px]">
                            {/* Days Labels */}
                            <div className="flex flex-col gap-[3px] text-[6px] font-black text-muted-foreground/20 uppercase pr-1 pt-[2px]">
                                <div className="h-2 flex items-center">Mon</div>
                                <div className="h-2" />
                                <div className="h-2 flex items-center">Wed</div>
                                <div className="h-2" />
                                <div className="h-2 flex items-center">Fri</div>
                                <div className="h-2" />
                                <div className="h-2" />
                            </div>

                            {/* The Grid */}
                            <div className="flex gap-[3px]">
                                {Array.from({ length: 52 }).map((_, weekIdx) => (
                                    <div key={weekIdx} className="flex flex-col gap-[3px]">
                                        {Array.from({ length: 7 }).map((_, dayIdx) => {
                                            const idx = weekIdx * 7 + dayIdx;
                                            const level = fullYearData[idx];
                                            return (
                                                <motion.div
                                                    key={dayIdx}
                                                    initial={{ opacity: 0, scale: 0.8 }}
                                                    animate={{ opacity: 1, scale: 1 }}
                                                    transition={{ delay: idx * 0.0005 }}
                                                    className={cn(
                                                        "w-[8px] h-[8px] rounded-[1.5px] transition-all duration-700",
                                                        getColor(level)
                                                    )}
                                                />
                                            );
                                        })}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>
                </div>
                <div className="absolute right-0 top-0 bottom-0 w-8 bg-gradient-to-l from-slate-950/20 to-transparent pointer-events-none" />
            </div>

            <div className="flex items-center justify-between px-1 pt-3 border-t border-white/[0.05]">
                <p className="text-[6px] text-muted-foreground/30 font-black uppercase tracking-[0.2em]">Signal synchronization complete</p>
                <div className="flex items-center gap-2 text-[6px] text-muted-foreground/40 font-black uppercase tracking-wider">
                    <span>Low</span>
                    <div className="flex gap-0.5">
                        {[0, 1, 2, 3, 4].map(l => (
                            <div key={l} className={cn("w-1.5 h-1.5 rounded-[1px]", getColor(l))} />
                        ))}
                    </div>
                    <span>High</span>
                </div>
            </div>
        </div>
    );
};
