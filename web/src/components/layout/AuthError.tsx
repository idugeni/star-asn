import React from 'react';
import { HiOutlineShieldCheck, HiOutlineArrowPath } from "react-icons/hi2";
import { Button } from '@/components/ui/button';
import { Card, CardTitle, CardDescription } from '@/components/ui/card';

interface AuthErrorProps {
    error: string;
}

export const AuthError = ({ error }: AuthErrorProps) => (
    <div className="flex items-center justify-center w-full p-4">
        <Card className="max-w-sm border-red-500/20 bg-red-500/5 backdrop-blur-3xl p-8 text-center space-y-6 overflow-hidden relative">
            <div className="absolute inset-0 bg-red-500/5 animate-pulse m-0" />
            <HiOutlineShieldCheck className="mx-auto h-16 w-16 text-red-500 relative z-10" />
            <div className="relative z-10 space-y-2">
                <CardTitle className="text-red-500 text-3xl font-black uppercase tracking-tighter">Access Denied</CardTitle>
                <CardDescription className="text-red-300/60 leading-relaxed font-medium">
                    {error}
                </CardDescription>
            </div>
            <Button 
                variant="destructive" 
                className="w-full h-12 relative z-10 font-black uppercase tracking-widest text-[10px]"
                onClick={() => window.location.reload()}
            >
                <HiOutlineArrowPath className="mr-2 h-4 w-4" /> Reset Authorization
            </Button>
        </Card>
    </div>
);
