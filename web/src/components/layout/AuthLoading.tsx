import React from 'react';
import { motion } from 'motion/react';


export const AuthLoading = () => (
    <div className="flex flex-col items-center justify-center min-h-[50vh] w-full relative">
        {/* Background Atmosphere */}
        <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-[500px] h-[500px] bg-blue-600/5 blur-[120px] rounded-full" />
        
        <motion.div 
            initial={{ scale: 0.8, opacity: 0 }}
            animate={{ scale: [1, 1.05, 1], opacity: 1 }}
            transition={{ duration: 3, repeat: Infinity, ease: "easeInOut" }}
            className="relative"
        >
            <div className="absolute inset-0 bg-primary/10 blur-3xl rounded-full" />
            <img 
                src="/logo.png" 
                alt="Star-ASN Logo" 
                className="h-28 w-28 relative z-10 drop-shadow-[0_0_25px_rgba(59,130,246,0.5)]"
            />
            
            <motion.div 
                animate={{ rotate: 360 }}
                transition={{ duration: 6, repeat: Infinity, ease: "linear" }}
                className="absolute -inset-4 border border-dashed border-blue-500/20 rounded-full"
            />
            <motion.div 
                animate={{ rotate: -360 }}
                transition={{ duration: 10, repeat: Infinity, ease: "linear" }}
                className="absolute -inset-8 border border-dotted border-white/5 rounded-full"
            />
        </motion.div>
        
        <motion.div 
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.5 }}
            className="mt-12 text-center"
        >
            <h1 className="text-4xl font-black italic tracking-[-0.05em] text-white">
                STAR<span className="text-blue-500">ASN</span>
            </h1>
            <div className="flex items-center gap-3 mt-4">
                <span className="text-[10px] text-slate-600 font-bold uppercase tracking-[0.5em]">Establishing Neural Link</span>
                <span className="w-1.5 h-1.5 bg-blue-500 rounded-full animate-pulse" />
            </div>
        </motion.div>
    </div>
);
