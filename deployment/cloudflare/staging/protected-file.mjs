import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {ROOT} from './artifact.mjs';
import {ensure,GateBlocked,GateFailure} from './errors.mjs';
const C=fs.constants;
const unavailable=e=>{if(e instanceof GateFailure||e instanceof GateBlocked)throw e;throw new GateBlocked('PROTECTED_FILE_UNAVAILABLE');};
const privateMode=st=>st.uid===process.getuid()&&(st.mode&0o077)===0;
// Linux descriptor-relative traversal: neither an ancestor nor the final path
// may be followed through a symlink. No pathname is reopened after validation.
function directory(dir,{work=false}={}){
  if(process.platform!=='linux')throw new GateBlocked('PROTECTED_FILES_REQUIRE_LINUX');
  let fd=fs.openSync('/',C.O_RDONLY|C.O_DIRECTORY|C.O_NOFOLLOW);
  const parts=path.resolve(dir).split('/').filter(Boolean),workParts=path.resolve(ROOT,'work').split('/').filter(Boolean);
  try{
    for(const [i,part] of parts.entries()){
      const p=`/proc/self/fd/${fd}/${part}`;
      if(work&&i===workParts.length-1)try{fs.mkdirSync(p,{mode:0o700});}catch(e){if(e.code!=='EEXIST')throw e;}
      const next=fs.openSync(p,C.O_RDONLY|C.O_DIRECTORY|C.O_NOFOLLOW);
      fs.closeSync(fd);fd=next;
      if(work&&i>=workParts.length-1)ensure(privateMode(fs.fstatSync(fd)),'PROTECTED_DIRECTORY_PERMISSIONS');
    }
    return fd;
  }catch(e){fs.closeSync(fd);throw e;}
}
function workParent(file){
  const absolute=path.resolve(file),root=path.resolve(ROOT,'work');
  ensure(absolute.startsWith(root+path.sep),'OUTPUT_MUST_BE_UNDER_REPOSITORY_WORK');
  return {absolute,fd:directory(path.dirname(absolute),{work:true})};
}
export function readProtected(file,{publicExample=false}={}){
  if(!file)throw new GateBlocked('PROTECTED_FILE_REQUIRED');
  let parent,fd;
  try{
    parent=directory(path.dirname(path.resolve(file)));
    fd=fs.openSync(`/proc/self/fd/${parent}/${path.basename(file)}`,C.O_RDONLY|C.O_NOFOLLOW|C.O_NONBLOCK);
    const st=fs.fstatSync(fd);
    ensure(st.isFile()&&st.nlink===1&&(publicExample||privateMode(st))&&st.size<64000,'PROTECTED_FILE_PERMISSIONS');
    const bytes=Buffer.alloc(64000);let size=0,n;
    while(size<bytes.length&&(n=fs.readSync(fd,bytes,size,bytes.length-size,null)))size+=n;
    const after=fs.fstatSync(fd);
    ensure(size===st.size&&size<64000&&after.size===st.size&&after.mtimeMs===st.mtimeMs&&after.ctimeMs===st.ctimeMs,'PROTECTED_FILE_CHANGED');
    return bytes.subarray(0,size).toString('utf8');
  }catch(e){unavailable(e);}finally{if(fd!==undefined)fs.closeSync(fd);if(parent!==undefined)fs.closeSync(parent);}
}
function openNew(fd,name){
  const file=fs.openSync(`/proc/self/fd/${fd}/${name}`,C.O_WRONLY|C.O_CREAT|C.O_EXCL|C.O_NOFOLLOW,0o600);
  try{ensure(privateMode(fs.fstatSync(file)),'PROTECTED_FILE_PERMISSIONS');return file;}catch(e){fs.closeSync(file);throw e;}
}
function writeNew(fd,name,body){
  const file=openNew(fd,name);
  try{fs.writeFileSync(file,body);}finally{fs.closeSync(file);}
}
// Fresh directory only; existing output (including hard links) is never rewritten.
export function writeProtectedDirectory(out,files){
  let parent,fd;
  try{
    const p=workParent(out);parent=p.fd;
    fs.mkdirSync(`/proc/self/fd/${parent}/${path.basename(p.absolute)}`,{mode:0o700});
    fd=fs.openSync(`/proc/self/fd/${parent}/${path.basename(p.absolute)}`,C.O_RDONLY|C.O_DIRECTORY|C.O_NOFOLLOW);
    ensure(privateMode(fs.fstatSync(fd)),'PROTECTED_DIRECTORY_PERMISSIONS');
    for(const [name,body] of Object.entries(files)){
      ensure(/^(?:[a-z-]+\/)?[a-z.-]+$/.test(name),'INVALID_OUTPUT_NAME');
      const parts=name.split('/');let sub;
      try{
        if(parts.length===2){const p=`/proc/self/fd/${fd}/${parts[0]}`;try{fs.mkdirSync(p,{mode:0o700});}catch(e){if(e.code!=='EEXIST')throw e;}sub=fs.openSync(p,C.O_RDONLY|C.O_DIRECTORY|C.O_NOFOLLOW);ensure(privateMode(fs.fstatSync(sub)),'PROTECTED_DIRECTORY_PERMISSIONS');}
        writeNew(sub??fd,parts.at(-1),body);
      }finally{if(sub!==undefined)fs.closeSync(sub);}
    }
  }catch(e){unavailable(e);}finally{if(fd!==undefined)fs.closeSync(fd);if(parent!==undefined)fs.closeSync(parent);}
}
// Reserve an exclusive descriptor BEFORE input reads or network activity. The
// same descriptor is completed once; a killed process leaves an invalid empty
// receipt, never a passing proof. A repeat run must choose a fresh filename.
export function reserveReceipt(file){
  if(!file)throw new GateBlocked('PROTECTED_RECEIPT_REQUIRED');
  let parent,fd;
  try{const p=workParent(file);parent=p.fd;fd=openNew(parent,path.basename(p.absolute));}
  catch(e){unavailable(e);}finally{if(parent!==undefined)fs.closeSync(parent);}
  return receipt=>{
    ensure(fd!==undefined,'RECEIPT_ALREADY_COMPLETED');
    try{fs.writeFileSync(fd,JSON.stringify(receipt,null,2)+'\n');}
    catch(e){unavailable(e);}finally{fs.closeSync(fd);fd=undefined;}
  };
}
export function writeReceipt(file,receipt){reserveReceipt(file)(receipt);}
export function receiptArgument(args,{revoked=false}={}){
  const rest=revoked?args.filter(x=>x!=='--revoked'):args;
  if(args.filter(x=>x==='--revoked').length>(revoked?1:0)||rest.length!==2||rest[0]!=='--receipt'||!rest[1]||rest[1].startsWith('--'))throw new GateBlocked('PROTECTED_RECEIPT_REQUIRED');
  return rest[1];
}
export function prepareWork(){
  let fd;try{fd=directory(path.join(ROOT,'work'),{work:true});}
  catch(e){unavailable(e);}finally{if(fd!==undefined)fs.closeSync(fd);}
}
if(process.argv[1]===fileURLToPath(import.meta.url)){
  try{if(process.argv.length!==3||process.argv[2]!=='--init-work')throw new GateBlocked('INVALID_INIT_ARGUMENTS');prepareWork();console.log('PASS: private work directory ready');}
  catch{console.log('BLOCKED: private work directory unavailable');process.exitCode=2;}
}
