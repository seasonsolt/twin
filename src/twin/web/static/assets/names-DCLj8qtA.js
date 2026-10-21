const a=new Intl.Collator("zh-CN"),n=(t,o)=>a.compare(t,o);function c(t,o){return[...t].sort((r,s)=>n(o(r),o(s)))}export{n as b,c as s};
