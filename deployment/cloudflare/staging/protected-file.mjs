import fs from 'node:fs';
import {ensure,GateBlocked} from './errors.mjs';
export function readProtected(file){
  if(!file)throw new GateBlocked('PROTECTED_FILE_REQUIRED');
  const st=fs.lstatSync(file);
  ensure(st.isFile()&&!st.isSymbolicLink()&&(st.mode&0o077)===0&&st.size<64000,'PROTECTED_FILE_PERMISSIONS');
  return fs.readFileSync(file,'utf8');
}
