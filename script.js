"use strict";
const API_URL=(location.protocol.indexOf("http")===0&&location.hostname&&location.port!=="5500")?location.origin:"http://"+(["localhost","127.0.0.1"].includes(location.hostname)?location.hostname:"127.0.0.1")+":5000"; // served by ALEX itself -> same address; port 5500 -> backend on 5000
let authenticated=false,selectedVoice="male",isListening=false,isSpeaking=false,isProcessing=false;
let recognition=null,recognitionStarting=false,shouldListen=true,recognitionBlocked=false,restartTimer=null;
let cameraStream=null,alexAudio=null,speechRequestId=0,chatHistory=[],welcomeShown=false;
let computerControlEnabled=false,systemInformation=null,tasks=[],memoryData=[],learningData=null,skillsData=[];
let lastVoiceCommand="",lastVoiceCommandTime=0;
const $=id=>document.getElementById(id);
const el={status:$("status"),clock:$("clock"),chatMessages:$("chatMessages"),chatInput:$("chatInput"),sendBtn:$("sendBtn"),voiceFemale:$("voiceFemale"),voiceMale:$("voiceMale"),micBtn:$("micBtn"),avatarMicBtn:$("avatarMicBtn"),avatarMicStatus:$("avatarMicStatus"),voiceStatus:$("voiceStatus"),listenStatus:$("listenStatus"),cameraStatus:$("cameraStatus"),cameraBtn:$("cameraBtn"),cameraStopBtn:$("cameraStopBtn"),cameraVideo:$("cameraVideo"),avatarStatus:$("avatarStatus"),hologram:document.querySelector(".hologram-container")};
function normalizeCommand(v){return String(v||"").toLowerCase().trim().replace(/[.,!?।]/g,"").replace(/\s+/g," ")}
function stripWakeWord(v){return String(v||"").trim().replace(/^(?:(?:hey|hello|hi)\s+)?alex[\s,:-]*/i,"").trim()}
function setStatus(m,ok=true){if(el.status){el.status.textContent=m;el.status.classList.toggle("offline",!ok)}}
function setAvatarStatus(m){if(el.avatarStatus)el.avatarStatus.textContent=m}
function setVoiceStatus(m){if(el.voiceStatus)el.voiceStatus.textContent=m;if(el.listenStatus)el.listenStatus.textContent=m}
function setThinking(on){el.hologram?.classList.toggle("is-thinking",!!on);$("avatarScreen")?.classList.toggle("is-thinking",!!on);if(on)setAvatarStatus("THINKING");else if(!isSpeaking)setAvatarStatus(isListening?"LISTENING":"ONLINE")}
function setSpeaking(on){isSpeaking=!!on;el.hologram?.classList.toggle("is-speaking",isSpeaking);$("avatarScreen")?.classList.toggle("is-speaking",isSpeaking);if(on)setAvatarStatus("SPEAKING");else if(!isProcessing)setAvatarStatus(isListening?"LISTENING":"ONLINE")}
function safeError(e){return e?.message||"Unexpected error"}
function addMessage(role,text){if(!el.chatMessages)return null;const n=document.createElement("div");n.className=role==="user"?"user-message":"alex-message";n.style.whiteSpace="pre-wrap";n.textContent=String(text??"");el.chatMessages.appendChild(n);el.chatMessages.scrollTop=el.chatMessages.scrollHeight;return n}
function updateMessage(n,t){if(n){n.textContent=String(t??"");el.chatMessages.scrollTop=el.chatMessages.scrollHeight}}
function addToHistory(role,content){chatHistory.push({role,content:String(content??"")});if(chatHistory.length>20)chatHistory=chatHistory.slice(-20)}
async function apiRequest(endpoint,options={}){const config={...options,credentials:"include",headers:{...(options.headers||{})}};if(options.body&&!(options.body instanceof FormData))config.headers["Content-Type"]="application/json";let response;try{response=await fetch(API_URL+endpoint,config)}catch(e){setStatus("SERVER OFFLINE",false);throw new Error("Cannot connect to ALEX. Check that app.py is running.")}const ct=response.headers.get("content-type")||"";let data=ct.includes("application/json")?await response.json():ct.startsWith("text/")?await response.text():await response.blob();if(response.status===401){authenticated=false;stopAutomaticListening();showLoginScreen();throw new Error("Session expired. Please log in again.")}if(!response.ok)throw new Error(data?.error||data?.message||`Server error ${response.status}`);return data}
function showLoginScreen(){if($("alexLoginOverlay"))return;const o=document.createElement("div");o.id="alexLoginOverlay";o.style.cssText="position:fixed;inset:0;z-index:20000;display:grid;place-items:center;background:#020811f5;font-family:Arial";o.innerHTML=`<div style="width:90%;max-width:380px;padding:30px;border:1px solid #00eaff;border-radius:16px;background:#071323;text-align:center;color:white"><h1 style="color:#00eaff;letter-spacing:5px">ALEX</h1><p style="margin:14px;color:#9bcbd8">PERSONAL AI AUTHENTICATION</p><input id="alexLoginPassword" type="password" placeholder="Enter ALEX password" style="width:100%;padding:13px;margin:10px 0;background:#020b16;color:white;border:1px solid #00bfe8;border-radius:7px"><button id="alexLoginButton" style="width:100%;padding:13px;background:#00c8ed;border:0;border-radius:7px;font-weight:bold">LOGIN</button><p id="alexLoginMessage" style="color:#ff7272;margin-top:12px"></p></div>`;document.body.appendChild(o);const p=$("alexLoginPassword"),b=$("alexLoginButton"),m=$("alexLoginMessage");async function login(){if(!p.value.trim()){m.textContent="Enter your password.";return}b.disabled=true;b.textContent="CONNECTING...";try{const r=await apiRequest("/login",{method:"POST",body:JSON.stringify({password:p.value.trim()})});if(!r.success)throw Error(r.error||"Login failed");authenticated=true;selectedVoice=r.voice||"male";o.remove();updateVoiceButtons();setStatus("CONNECTED");await loadInitialData();showWelcomeMessage();startAutomaticListening()}catch(e){m.textContent=safeError(e)}finally{b.disabled=false;b.textContent="LOGIN"}}b.onclick=login;p.addEventListener("keydown",e=>{if(e.key==="Enter")login()});p.focus()}
async function checkSession(){try{const r=await apiRequest("/session");authenticated=!!r.authenticated;selectedVoice=r.voice||"male";updateVoiceButtons();if(!authenticated){setStatus("LOGIN REQUIRED",false);showLoginScreen();return false}setStatus("CONNECTED");setAvatarStatus("ONLINE");return true}catch(e){authenticated=false;setStatus("SERVER OFFLINE",false);setAvatarStatus("OFFLINE");console.warn(e);return false}}
async function loadInitialData(){for(const p of ["/health","/computer-control","/system-info"]){try{console.log("ALEX startup",p,await apiRequest(p))}catch(e){console.warn(p,e.message)}}}
function showWelcomeMessage(){if(!authenticated||welcomeShown)return;welcomeShown=true;const t="Welcome back! I am ALEX. How can I help you?";addMessage("assistant",t);setAvatarStatus("ONLINE");setVoiceStatus("READY");speakText(t)}
async function askALEX(message){if(!authenticated){showLoginScreen();return}if(!message||isProcessing)return;isProcessing=true;pauseRecognition();addMessage("user",message);setThinking(true);setStatus("PROCESSING");const pending=addMessage("assistant","ALEX is thinking...");try{const r=await apiRequest("/ask",{method:"POST",body:JSON.stringify({message,history:chatHistory})});if(r.success===false)throw Error(r.error||"AI request failed");const answer=r.response||r.answer||"I could not generate a response.";updateMessage(pending,answer);addToHistory("user",message);addToHistory("assistant",answer);setStatus("CONNECTED");speakText(answer)}catch(e){updateMessage(pending,"ALEX ERROR: "+safeError(e));setStatus("ERROR",false);console.error(e)}finally{isProcessing=false;setThinking(false);if(!isSpeaking)scheduleRecognitionRestart(900)}}
function showAvatar(){const s=$("avatarScreen");if(!s)return;s.classList.add("visible");s.setAttribute("aria-hidden","false");document.body.style.overflow="hidden";setAvatarMode(currentAvatarMode);return true}
function hideAvatar(){const s=$("avatarScreen");if(!s)return;s.classList.remove("visible");s.setAttribute("aria-hidden","true");document.body.style.overflow="";return true}
let currentAvatarMode="normal";
const avatarModes={normal:{label:"NORMAL MODE",description:"ALEX is standing by.",color:"#00eaff"},danger:{label:"DANGER MODE",description:"Threat alert mode activated.",color:"#ff344f"},fighting:{label:"FIGHTING MODE",description:"Combat stance activated. Simulation only.",color:"#ff6b1a"},virus:{label:"VIRUS MODE",description:"Cyber threat visualization activated.",color:"#b44cff"},scanning:{label:"SCANNING MODE",description:"Scanning visualization activated.",color:"#00ffae"},power:{label:"POWER MODE",description:"Maximum power visualization activated.",color:"#ffd84a"}};
function setAvatarMode(mode){if(!avatarModes[mode])mode="normal";currentAvatarMode=mode;const s=$("avatarScreen"),m=avatarModes[mode];s.dataset.mode=mode;$("avatarModeLabel").textContent=m.label;$("modeDescription").textContent=m.description;document.querySelectorAll(".mode-button").forEach(b=>b.classList.toggle("active",b.dataset.mode===mode));return true}
function handleAvatarCommand(message){const t=normalizeCommand(message);if(/\b(show|open|display)\b.*\b(your )?avatar\b|\bavatar dikhao\b|\bapna avatar dikhao\b/.test(t)){showAvatar();return "ALEX avatar is now on screen."}if(/\b(hide|close|exit)\b.*\b(your )?avatar\b|\bavatar chhupao\b|\bavatar band karo\b/.test(t)){hideAvatar();return "ALEX avatar hidden."}if(/\b(rotate|360|turn around|spin)\b/.test(t)){startAvatarSpin();return "Rotating my avatar in 360 degree view."}const aliases={normal:["normal"],danger:["danger"],fighting:["fighting","fight","combat"],virus:["virus"],scanning:["scanning","scan"],power:["power"]};for(const [mode,words] of Object.entries(aliases)){if(words.some(w=>t.includes(w))&&(/\b(mode|avatar)\b/.test(t)||t.startsWith("switch")||t.startsWith("change")||t.startsWith("activate")||t.startsWith("go to"))){setAvatarMode(mode);return `${mode} mode activated.`}}return null}
function getCameraCommand(m){const t=normalizeCommand(m);if(/\b(stop|close|disable|turn off)\b.*\b(camera|cam)\b/.test(t)||/camera band karo|camera off karo/.test(t))return"stop";if(/\b(start|open|activate|turn on)\b.*\b(camera|cam)\b/.test(t)||/camera kholo|camera on karo/.test(t))return"start";if(/what can you see|look at this|camera se dekho|mere samne kya hai/.test(t))return"analyze";return null}
async function handleCameraCommand(m){const c=getCameraCommand(m);if(!c)return false;if(c==="stop"){stopCamera();speakText("Camera has been turned off.");return true}if(c==="start"){const ok=await startCamera();speakText(ok?"Camera is now active.":"I could not start the camera.");return true}await analyzeCameraImage(true);return true}
function isLikelyLocalCommand(m){return /^(open|launch|start|run|search|google)\b|\b(chrome|youtube|gmail|notepad|calculator|paint|explorer|screenshot|volume|brightness|mouse|keyboard|shutdown|restart|lock computer)\b/i.test(m)}
async function executeLocalCommand(message){try{const r=await apiRequest("/command",{method:"POST",body:JSON.stringify({command:message})});if(!r.handled)return false;const a=r.response||"Command completed.";addMessage("user",message);addMessage("assistant",a);addToHistory("user",message);addToHistory("assistant",a);if(r.success!==false)speakText(a);return true}catch(e){addMessage("assistant","Computer command error: "+safeError(e));return true}}
function handleListeningCommand(m){const t=normalizeCommand(m);if(/stop listening|microphone off|mic off|sunna band karo/.test(t)){stopAutomaticListening();return true}if(/start listening|microphone on|mic on|meri baat suno/.test(t)){startAutomaticListening();return true}if(/stop speaking|be quiet|chup ho jao/.test(t)){stopSpeech();return true}return false}

// ==========================================
// ALEX MAPS + PHONE / WHATSAPP QUICK SKILLS
// Integrated into the existing ALEX command flow.
// ==========================================
function alexSkillReply(message){
  addMessage("assistant",message);
  if(typeof speakText==="function") speakText(message);
}
function alexExtractPhone(text){
  const m=String(text||"").match(/(?:\+?\d[\d\s().-]{7,}\d)/);
  return m ? m[0].replace(/\D/g,"") : "";
}
function alexHandleMapsCalling(raw){
  const t=normalizeCommand(raw);
  // Maps: open, search, and route commands.
  if(/^(open|launch|show)\s+(google\s+)?maps$|^(maps kholo|google maps kholo)$/.test(t)){
    window.open("https://www.google.com/maps","_blank","noopener");
    alexSkillReply("Opening Google Maps."); return true;
  }
  if(/\b(my location|current location|where am i|meri location|current jagah)\b/.test(t)){
    if(!navigator.geolocation){alexSkillReply("This browser does not support location access.");return true;}
    alexSkillReply("Please allow location access in your browser. I will show your location on Google Maps.");
    navigator.geolocation.getCurrentPosition(pos=>{
      const {latitude,longitude}=pos.coords;
      window.open(`https://www.google.com/maps/@${latitude},${longitude},16z`,`_blank`,`noopener`);
    },()=>alexSkillReply("Location permission was denied. Allow location access and try again."),{enableHighAccuracy:true,timeout:12000});
    return true;
  }
  let destination="";
  const routeMatch=t.match(/(?:show me the route to|directions to|navigate to|route to|take me to|mujhe|ka route dikhao|ka rasta dikhao)\s+(.+)/i);
  const routeHindi=t.match(/^(.+?)\s+(?:ka route dikhao|ka rasta dikhao|tak ka rasta)$/i);
  if(routeMatch) destination=routeMatch[1].trim();
  else if(routeHindi) destination=routeHindi[1].trim();
  if(destination){
    const url="https://www.google.com/maps/dir/?api=1&destination="+encodeURIComponent(destination)+"&travelmode=driving";
    window.open(url,"_blank","noopener");
    alexSkillReply(`Showing directions to ${destination} in Google Maps.`); return true;
  }
  const searchMatch=t.match(/(?:search|find|show|look for)\s+(.+?)\s+(?:on|in)\s+(?:google\s+)?maps$/i);
  if(searchMatch){
    const place=searchMatch[1].trim();
    window.open("https://www.google.com/maps/search/?api=1&query="+encodeURIComponent(place),"_blank","noopener");
    alexSkillReply(`Searching ${place} on Google Maps.`); return true;
  }
  // Phone and WhatsApp actions. A confirmation is always required.
  const wantsWhatsApp=/\b(whatsapp|whats app)\b/.test(t) && /\b(call|phone|ring|dial|karo|lagao)\b/.test(t);
  const wantsPhone=/\b(call|phone|dial|ring|number milao|call karo|phone lagao)\b/.test(t) && !wantsWhatsApp;
  if(wantsWhatsApp || wantsPhone){
    const number=alexExtractPhone(raw);
    if(!number || number.length<8 || number.length>15){
      alexSkillReply("Please say the full phone number with country code. I cannot access your phone contacts from this browser yet."); return true;
    }
    if(wantsWhatsApp){
      if(!window.confirm(`Open WhatsApp chat with +${number}? Then tap the phone icon in WhatsApp to start the call.`)) return true;
      window.open(`https://wa.me/${number}`,"_blank","noopener");
      alexSkillReply("Opening the WhatsApp chat. Tap the phone icon in WhatsApp to place the call; I cannot start a WhatsApp call automatically from this browser.");
      return true;
    }
    if(!window.confirm(`Open your phone dialer for +${number}? You must press Call on your phone to place the call.`)) return true;
    window.location.href="tel:+"+number;
    alexSkillReply("Opening the phone dialer. Press Call on your phone when you are ready.");
    return true;
  }
  return false;
}

async function processUserMessage(raw,source="text"){const original=String(raw||"").trim(),message=stripWakeWord(original);if(!message)return;const norm=normalizeCommand(message),now=Date.now();if(source==="voice"&&norm===lastVoiceCommand&&now-lastVoiceCommandTime<1800)return;lastVoiceCommand=norm;lastVoiceCommandTime=now;if(!authenticated){showLoginScreen();return}if(alexHandleMapsCalling(message))return;const avatarReply=handleAvatarCommand(message);if(avatarReply){if(source==="text"){addMessage("user",message);addMessage("assistant",avatarReply)}speakText(avatarReply);return}if(handleListeningCommand(message))return;if(await handleCameraCommand(message))return;if(isLikelyLocalCommand(message)&&await executeLocalCommand(message))return;await askALEX(message)}
async function sendMessage(){if(!el.chatInput||isProcessing)return;const m=el.chatInput.value.trim();if(!m)return;el.chatInput.value="";await processUserMessage(m,"text")}
function initializeChatEvents(){el.sendBtn?.addEventListener("click",sendMessage);el.chatInput?.addEventListener("keydown",e=>{if(e.key==="Enter"&&!e.shiftKey){e.preventDefault();sendMessage()}})}
function updateVoiceButtons(){el.voiceMale?.classList.toggle("active",selectedVoice==="male");el.voiceFemale?.classList.toggle("active",selectedVoice==="female")}
async function setVoice(v){if(!["male","female"].includes(v))return;selectedVoice=v;updateVoiceButtons();try{await apiRequest("/set-voice",{method:"POST",body:JSON.stringify({voice:v})});setVoiceStatus(v.toUpperCase()+" VOICE SELECTED")}catch(e){setVoiceStatus("VOICE SETTING ERROR");console.warn(e)}}
function initializeVoiceButtons(){el.voiceMale?.addEventListener("click",()=>setVoice("male"));el.voiceFemale?.addEventListener("click",()=>setVoice("female"))}
async function speakText(text){if(!authenticated||!text)return;stopSpeech();const id=++speechRequestId;setSpeaking(true);setVoiceStatus("SPEAKING");try{const r=await apiRequest("/speak",{method:"POST",body:JSON.stringify({text:String(text),voice:selectedVoice})});if(id!==speechRequestId)return;let url=r.audio_url?(r.audio_url.startsWith("http")?r.audio_url:API_URL+r.audio_url):r.audio?"data:audio/mpeg;base64,"+r.audio:null;if(!url)throw Error("Audio response was empty");alexAudio=new Audio(url);alexAudio.onended=()=>{if(id!==speechRequestId)return;alexAudio=null;setSpeaking(false);setVoiceStatus("READY");scheduleRecognitionRestart(500)};alexAudio.onerror=()=>{if(id!==speechRequestId)return;alexAudio=null;setSpeaking(false);setVoiceStatus("VOICE ERROR");scheduleRecognitionRestart(700)};await alexAudio.play()}catch(e){console.warn("Speech:",e);if(id===speechRequestId){setSpeaking(false);setVoiceStatus("VOICE UNAVAILABLE");scheduleRecognitionRestart(700)}}}
function stopSpeech(){speechRequestId++;if(alexAudio){alexAudio.pause();alexAudio.currentTime=0;alexAudio=null}if("speechSynthesis"in window)window.speechSynthesis.cancel();setSpeaking(false)}
function initializeSpeechRecognition(){const SR=window.SpeechRecognition||window.webkitSpeechRecognition;if(!SR){setVoiceStatus("VOICE RECOGNITION NOT SUPPORTED");return false}recognition=new SR();recognition.lang="hi-IN";recognition.continuous=true;recognition.interimResults=true;recognition.maxAlternatives=1;recognition.onstart=()=>{recognitionStarting=false;isListening=true;setVoiceStatus("LISTENING");setAvatarStatus("LISTENING");el.micBtn?.classList.add("active");el.avatarMicBtn?.classList.add("active");if(el.avatarMicStatus)el.avatarMicStatus.textContent="LISTENING..."};recognition.onresult=async e=>{let transcript="";for(let i=e.resultIndex;i<e.results.length;i++)if(e.results[i].isFinal)transcript+=e.results[i][0].transcript;transcript=transcript.trim();if(!transcript)return;pauseRecognition();await processUserMessage(transcript,"voice")};recognition.onerror=e=>{recognitionStarting=false;if(e.error==="not-allowed"||e.error==="service-not-allowed"){recognitionBlocked=true;shouldListen=false;isListening=false;setVoiceStatus("MICROPHONE PERMISSION DENIED");return}if(shouldListen&&!recognitionBlocked)scheduleRecognitionRestart(1200)};recognition.onend=()=>{recognitionStarting=false;isListening=false;el.micBtn?.classList.remove("active");el.avatarMicBtn?.classList.remove("active");if(el.avatarMicStatus)el.avatarMicStatus.textContent="MIC READY";if(shouldListen&&!recognitionBlocked)scheduleRecognitionRestart(800);else setVoiceStatus("MICROPHONE OFF")};return true}
function startAutomaticListening(){shouldListen=true;recognitionBlocked=false;if(!recognition&&!initializeSpeechRecognition())return;startRecognition()}
function startRecognition(){if(!recognition||!authenticated||!shouldListen||recognitionBlocked||recognitionStarting||isListening||isSpeaking||isProcessing)return;clearTimeout(restartTimer);try{recognitionStarting=true;recognition.start()}catch(e){recognitionStarting=false}}
function pauseRecognition(){clearTimeout(restartTimer);if(recognition&&(isListening||recognitionStarting)){try{recognition.stop()}catch(e){}}isListening=false;recognitionStarting=false;el.micBtn?.classList.remove("active");el.avatarMicBtn?.classList.remove("active");if(el.avatarMicStatus)el.avatarMicStatus.textContent="MIC READY"}
function stopAutomaticListening(){shouldListen=false;clearTimeout(restartTimer);pauseRecognition();setVoiceStatus("MICROPHONE OFF")}
function scheduleRecognitionRestart(delay=800){clearTimeout(restartTimer);if(!shouldListen||!authenticated||recognitionBlocked)return;restartTimer=setTimeout(()=>{if(!isSpeaking&&!isProcessing)startRecognition()},delay)}
function initializeMicrophoneButton(){const toggleMic=()=>shouldListen?stopAutomaticListening():startAutomaticListening();el.micBtn?.addEventListener("click",toggleMic);el.avatarMicBtn?.addEventListener("click",toggleMic)}
async function startCamera(){if(!navigator.mediaDevices?.getUserMedia){setCameraStatus("CAMERA NOT SUPPORTED");return false}try{stopCamera();cameraStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"user",width:{ideal:1280},height:{ideal:720}},audio:false});if(el.cameraVideo){el.cameraVideo.srcObject=cameraStream;el.cameraVideo.style.display="block";await el.cameraVideo.play()}setCameraStatus("CAMERA ACTIVE");if(el.cameraBtn)el.cameraBtn.disabled=true;if(el.cameraStopBtn)el.cameraStopBtn.disabled=false;return true}catch(e){console.error(e);setCameraStatus(e.name==="NotAllowedError"?"CAMERA PERMISSION DENIED":"CAMERA ERROR");return false}}
function stopCamera(){cameraStream?.getTracks().forEach(t=>t.stop());cameraStream=null;if(el.cameraVideo){el.cameraVideo.pause();el.cameraVideo.srcObject=null;el.cameraVideo.style.display="none"}if(el.cameraBtn)el.cameraBtn.disabled=false;if(el.cameraStopBtn)el.cameraStopBtn.disabled=true;setCameraStatus("CAMERA OFF")}
function setCameraStatus(m){if(el.cameraStatus)el.cameraStatus.textContent=m}
function captureCameraImage(){const v=el.cameraVideo;if(!v||!cameraStream||!v.videoWidth)return null;const c=document.createElement("canvas");c.width=v.videoWidth;c.height=v.videoHeight;const ctx=c.getContext("2d");if(!ctx)return null;ctx.drawImage(v,0,0,c.width,c.height);return c.toDataURL("image/jpeg",.85)}
async function analyzeCameraImage(voice=false){const image=captureCameraImage();if(!image){const m="Camera is not active. Start the camera first.";addMessage("assistant",m);if(voice)speakText(m);return false}try{setCameraStatus("ANALYZING IMAGE");const r=await apiRequest("/vision",{method:"POST",body:JSON.stringify({image,prompt:"Describe what is visible in this camera image."})});const a=r.response||r.description||r.answer||r.message||"I could not analyze the image.";addMessage("assistant",a);addToHistory("assistant",a);setCameraStatus("CAMERA ACTIVE");if(voice)speakText(a);return true}catch(e){const a="Vision error: "+safeError(e);addMessage("assistant",a);if(voice)speakText(a);setCameraStatus("VISION ERROR");return false}}
function initializeCameraButtons(){el.cameraBtn?.addEventListener("click",startCamera);el.cameraStopBtn?.addEventListener("click",stopCamera);$("analyzeCameraBtn")?.addEventListener("click",()=>analyzeCameraImage(true))}
async function getComputerControlStatus(){try{const r=await apiRequest("/computer-control");computerControlEnabled=r.enabled===true||r.available===true;return r}catch(e){return null}}
async function computerAction(action,data={}){try{setThinking(true);return await apiRequest("/computer-control",{method:"POST",body:JSON.stringify({action,...data})})}catch(e){return{success:false,error:safeError(e)}}finally{setThinking(false)}}
async function takeComputerScreenshot(){const r=await computerAction("screenshot");if(!r||r.success===false){addMessage("assistant","Could not capture computer screen.");return}const raw=r.image||r.screenshot||r.data;if(raw){const img=document.createElement("img");img.src=raw.startsWith("data:")?raw:"data:image/png;base64,"+raw;img.style.maxWidth="100%";const n=addMessage("assistant","Here is your computer screen:");n?.appendChild(img)}else addMessage("assistant",r.message||"Screenshot captured.")}
async function getSystemInformation(){try{const r=await apiRequest("/system-info");systemInformation=r;const box=$("systemInfo")||$("system-info");if(box)box.textContent=JSON.stringify(r,null,2);return r}catch(e){return null}}
async function loadTasks(){try{const r=await apiRequest("/tasks");tasks=Array.isArray(r)?r:r.tasks||[];const box=$("tasksList")||$("taskList");if(box){box.textContent="";tasks.forEach(t=>{const d=document.createElement("div");d.textContent=(t.title||t.name||t.task||"Task")+" — "+(t.completed?"Completed":"Pending");box.appendChild(d)})}return tasks}catch(e){return[]}}
async function createTask(title){if(!title?.trim())return null;try{const r=await apiRequest("/tasks",{method:"POST",body:JSON.stringify({title:title.trim(),task:title.trim()})});await loadTasks();return r}catch(e){return null}}
async function loadMemory(){try{const r=await apiRequest("/memory");memoryData=Array.isArray(r)?r:r.memories||r.memory||[];const box=$("memoryList")||$("memory-list");if(box)box.textContent=memoryData.map(x=>typeof x==="string"?x:x.content||x.text||JSON.stringify(x)).join("\n");return memoryData}catch(e){return[]}}
async function loadLearningData(){try{learningData=await apiRequest("/learning");const box=$("learningList")||$("learning-list");if(box)box.textContent=JSON.stringify(learningData,null,2);return learningData}catch(e){return null}}
async function loadSkills(){try{const r=await apiRequest("/skills");skillsData=Array.isArray(r)?r:r.skills||[];const box=$("skillsList")||$("skills-list");if(box)box.textContent=skillsData.map(x=>typeof x==="string"?x:x.name||x.title||JSON.stringify(x)).join("\n");return skillsData}catch(e){return[]}}
async function sendFeedback(message,rating=null){if(!message?.trim())return null;try{return await apiRequest("/feedback",{method:"POST",body:JSON.stringify({message:message.trim(),rating})})}catch(e){return null}}
async function refreshALEXData(){await Promise.allSettled([loadTasks(),loadMemory(),loadLearningData(),loadSkills(),getSystemInformation(),getComputerControlStatus()])}
let avatarYaw=0,draggingAvatar=false,dragStartX=0,dragStartYaw=0,avatarSpinTimer=null;
function applyAvatarYaw(){const turntable=$("avatarTurntable");if(turntable)turntable.style.setProperty("--avatar-yaw",`${avatarYaw}deg`)}
function startAvatarSpin(){const turntable=$("avatarTurntable"),btn=$("spinAvatarBtn");if(!turntable)return;turntable.classList.remove("auto-spin");void turntable.offsetWidth;turntable.classList.add("auto-spin");if(btn){btn.classList.add("active");btn.setAttribute("aria-pressed","true")}clearTimeout(avatarSpinTimer);avatarSpinTimer=setTimeout(()=>{turntable.classList.remove("auto-spin");if(btn){btn.classList.remove("active");btn.setAttribute("aria-pressed","false")}avatarYaw=(avatarYaw+360)%360;applyAvatarYaw()},4200)}
function initializeAvatarControls(){
  $("showAvatarBtn")?.addEventListener("click",showAvatar);$("hideAvatarBtn")?.addEventListener("click",hideAvatar);
  $("spinAvatarBtn")?.addEventListener("click",startAvatarSpin);
  document.querySelectorAll(".mode-button").forEach(b=>b.addEventListener("click",()=>setAvatarMode(b.dataset.mode)));
  const stage=document.querySelector(".avatar-stage");
  stage?.addEventListener("pointerdown",e=>{if(e.target.closest("button"))return;draggingAvatar=true;dragStartX=e.clientX;dragStartYaw=avatarYaw;stage.setPointerCapture?.(e.pointerId);stage.classList.add("dragging")});
  stage?.addEventListener("pointermove",e=>{if(!draggingAvatar)return;avatarYaw=dragStartYaw+(e.clientX-dragStartX)*.65;applyAvatarYaw()});
  const stopDrag=()=>{draggingAvatar=false;stage?.classList.remove("dragging")};stage?.addEventListener("pointerup",stopDrag);stage?.addEventListener("pointercancel",stopDrag);stage?.addEventListener("lostpointercapture",stopDrag);
  document.addEventListener("keydown",e=>{if(e.key==="Escape")hideAvatar()})
}
function updateClock(){if(el.clock)el.clock.textContent=new Date().toLocaleTimeString("en-IN",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}
async function logoutALEX(){try{await apiRequest("/logout",{method:"POST"})}catch(e){}stopAutomaticListening();stopSpeech();stopCamera();hideAvatar();authenticated=false;showLoginScreen()}
async function initializeALEX(){console.log("ALEX initializing");updateClock();setInterval(updateClock,1000);initializeChatEvents();initializeVoiceButtons();initializeMicrophoneButton();initializeCameraButtons();initializeAvatarControls();$("logoutBtn")?.addEventListener("click",logoutALEX);await checkSession();if(authenticated){await loadInitialData();await refreshALEXData();showWelcomeMessage();setStatus("ALEX ONLINE");startAutomaticListening()}console.log("ALEX ready")}
window.ALEX={initialize:initializeALEX,sendMessage,processUserMessage,startListening:startAutomaticListening,stopListening:stopAutomaticListening,startCamera,stopCamera,analyzeCameraImage,speak:speakText,stopSpeech,setVoice,showAvatar,hideAvatar,setAvatarMode,computerAction,takeComputerScreenshot,getSystemInformation,loadTasks,createTask,loadMemory,loadLearningData,loadSkills,sendFeedback,logout:logoutALEX};
if(document.readyState==="loading")document.addEventListener("DOMContentLoaded",initializeALEX,{once:true});else initializeALEX();

/* ===== ALEX PLUS: Iron Man 3D avatar ===== */
/* ALEX Transformer-style 3D avatar + sound (Three.js r128 + WebAudio). Hologram orb untouched. */
(()=>{
const stage=document.querySelector(".avatar-stage"),screen=document.getElementById("avatarScreen");
if(!stage||!screen)return;
// ---------- SOUND (synthesised, no audio files) ----------
const AC=window.AudioContext||window.webkitAudioContext;let ac=null;
const ctx=()=>{if(!AC)return null;if(!ac)ac=new AC();if(ac.state==="suspended")ac.resume().catch(()=>{});return ac};
function tone(f0,f1,d,type,v,at=0){const c=ctx();if(!c)return;const o=c.createOscillator(),g=c.createGain(),t=c.currentTime+at;o.type=type;o.frequency.setValueAtTime(f0,t);o.frequency.exponentialRampToValueAtTime(f1,t+d);g.gain.setValueAtTime(.0001,t);g.gain.exponentialRampToValueAtTime(v,t+d*.15);g.gain.exponentialRampToValueAtTime(.0001,t+d);o.connect(g);g.connect(c.destination);o.start(t);o.stop(t+d+.05)}
function noise(d,v,fc,at=0){const c=ctx();if(!c)return;const n=Math.floor(c.sampleRate*d),b=c.createBuffer(1,n,c.sampleRate),a=b.getChannelData(0);for(let i=0;i<n;i++)a[i]=(Math.random()*2-1)*(1-i/n);const s=c.createBufferSource(),f=c.createBiquadFilter(),g=c.createGain();s.buffer=b;f.type="bandpass";f.frequency.value=fc;f.Q.value=3;g.gain.value=v;s.connect(f);f.connect(g);g.connect(c.destination);s.start(c.currentTime+at)}
const SND={
 startup(){try{tone(45,110,1.4,"sawtooth",.25);tone(150,1100,1.1,"square",.07,.1);[.5,.8,1.05].forEach((a,i)=>noise(.18,.5,1800+i*700,a));[660,990,1320].forEach((f,i)=>tone(f,f*1.01,.9,"sine",.12,1.1+i*.12))}catch(e){}},
 transform(){try{for(let i=0;i<9;i++){tone(260+i*40,520+i*60,.16,"sawtooth",.08,i*.17);noise(.1,.45,900+i*250,i*.17+.1)}noise(.3,.7,300,1.6);tone(90,60,.4,"square",.2,1.6)}catch(e){}}};
SND.fx=n=>{try{({punch(){noise(.25,.6,1200);tone(160,50,.3,"square",.25,.12);noise(.15,.8,200,.14)},kick(){noise(.3,.6,900);tone(120,40,.35,"square",.3,.14)},slash(){noise(.45,.7,3000);tone(900,200,.4,"sawtooth",.1)},blast(){tone(80,900,.6,"sawtooth",.18);tone(60,30,.8,"square",.35,.6);noise(.6,.8,500,.6)},shield(){tone(200,520,1,"sine",.2);tone(400,1040,1,"sine",.08,.1);noise(.8,.2,4000)},jump(){tone(150,500,.3,"square",.12);tone(90,40,.3,"square",.35,.75);noise(.25,.6,250,.75)},roar(){tone(90,45,1.8,"sawtooth",.35);tone(130,60,1.6,"square",.12,.1);noise(1.7,.6,350)},uppercut(){noise(.3,.7,1500);tone(200,60,.3,"square",.3,.15)},roundhouse(){noise(.5,.7,1000);tone(130,40,.4,"square",.3,.3)},dodge(){noise(.25,.5,2500)},flip(){tone(200,700,.5,"sine",.12);noise(.4,.4,1800)},slam(){tone(300,40,.5,"square",.35,.45);noise(.7,.9,200,.5)},fly(){tone(80,160,1.5,"sawtooth",.15);noise(3,.35,700)},beam(){tone(400,1200,.4,"sawtooth",.12);tone(1200,1200,1.2,"sine",.12,.4);noise(1.4,.3,3500,.2)},combo(){noise(.2,.6,1300);noise(.2,.6,1300,.4);noise(.4,.7,1000,.8);tone(110,40,.3,"square",.3,.9)},salute(){tone(600,900,.3,"sine",.1)},victory(){[523,659,784,1046].forEach((f,i)=>tone(f,f,.4,"triangle",.15,i*.18))},charge(){tone(60,700,2,"sawtooth",.2);noise(2,.35,1200)},stance(){noise(.2,.5,800);tone(150,100,.25,"square",.15)}}[n]||(()=>{}))()}catch(e){}};
SND.mode=m=>{try{({danger(){for(let i=0;i<4;i++)tone(i%2?600:900,i%2?600:900,.18,"square",.1,i*.2)},fighting(){noise(.2,.8,2500);tone(100,50,.3,"square",.3,.1)},virus(){for(let i=0;i<8;i++)noise(.06,.6,500+Math.random()*3000,i*.07)},scanning(){tone(300,1500,.9,"sine",.15);tone(1500,1500,.2,"sine",.1,.9)},power(){tone(60,500,1.2,"sawtooth",.2);noise(.5,.5,1000,1.1)}}[m]||(()=>{}))()}catch(e){}};
let booted=false;const boot=()=>{if(booted)return;booted=true;SND.startup()};
addEventListener("pointerdown",boot,{once:true});addEventListener("keydown",boot,{once:true});
setTimeout(()=>{const c=ctx();if(c&&c.state==="running")boot()},400);
// ---------- public API ----------
const impl={emo(){},gest(){},reset(){}};
const api=window.ALEXAvatar3D={ready:true,setEmotion:(e,h)=>impl.emo(e,h),gesture:n=>{SND.fx(n);impl.gest(n);try{window.dispatchEvent(new CustomEvent("alex-action",{detail:{action:n}}))}catch(e){}},transform(){boot();SND.transform();impl.reset()}};
const acts=document.querySelector(".avatar-top-actions");
if(acts){const b=document.createElement("button");b.type="button";b.id="transformAvatarBtn";b.textContent="\u2699 TRANSFORM";b.addEventListener("click",()=>api.transform());acts.insertBefore(b,acts.firstChild)}
let lastMode=screen.dataset.mode||"normal";new MutationObserver(()=>{const m=screen.dataset.mode;if(m!==lastMode){lastMode=m;try{window.dispatchEvent(new CustomEvent("alex-action",{detail:{mode:m}}))}catch(e){}if(screen.classList.contains("visible"))SND.mode(m)}}).observe(screen,{attributes:true,attributeFilter:["data-mode"]});
let wasV=false;new MutationObserver(()=>{const v=screen.classList.contains("visible");if(v&&!wasV)api.transform();wasV=v}).observe(screen,{attributes:true,attributeFilter:["class"]});
// ---------- 3D ----------
const CDN="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js";
const load=()=>new Promise((ok,no)=>{if(window.THREE)return ok();const s=document.createElement("script");s.src=CDN;s.onload=ok;s.onerror=no;document.head.appendChild(s)});
load().then(init).catch(()=>console.warn("ALEX 3D: Three.js not loaded, classic avatar kept"));
function init(){
const T=THREE,COL={normal:0x00eaff,danger:0xff344f,fighting:0xff6b1a,virus:0xb44cff,scanning:0x00ffae,power:0xffd84a};
const ren=new T.WebGLRenderer({antialias:true,alpha:true});ren.setPixelRatio(Math.min(devicePixelRatio,2));
const cv=ren.domElement;cv.style.cssText="position:absolute;inset:0;width:100%;height:100%;z-index:2;cursor:grab;touch-action:none";
stage.appendChild(cv);const st=document.createElement("style");st.textContent=".avatar-stage.has-3d .avatar-turntable{display:none}";document.head.appendChild(st);stage.classList.add("has-3d");
const sc=new T.Scene(),cam=new T.PerspectiveCamera(32,1,.1,50);cam.position.set(0,1.1,10);cam.lookAt(0,.9,0);
sc.add(new T.AmbientLight(0x8899aa,.75));const dl=new T.DirectionalLight(0xffffff,1.1);dl.position.set(3,6,5);sc.add(dl);
const glow=new T.PointLight(COL.normal,1.6,14);glow.position.set(0,1.5,3);sc.add(glow);
const acc=new T.Color(COL.normal),accM=new T.MeshStandardMaterial({color:0x111111,emissive:acc,emissiveIntensity:1.4}),lineM=new T.LineBasicMaterial({color:acc});
const mk=c=>new T.MeshStandardMaterial({color:c,metalness:.8,roughness:.35});
const blue=mk(0xc9971c),red=mk(0xa31621),silver=mk(0xe3c16f),dark=mk(0x0a0f18);
const add=(p,m,x=0,y=0,z=0)=>{m.position.set(x,y,z);p.add(m);return m};
const box=(w,h,d,m,edge)=>{const g=new T.BoxGeometry(w,h,d),o=new T.Mesh(g,m);if(edge)o.add(new T.LineSegments(new T.EdgesGeometry(g),lineM));return o};
const cyl=(a,b,h,m)=>new T.Mesh(new T.CylinderGeometry(a,b,h,18),m),sph=(r,m)=>new T.Mesh(new T.SphereGeometry(r,20,16),m);
const glass=new T.MeshStandardMaterial({color:0x58b8ff,metalness:.9,roughness:.1,transparent:true,opacity:.75,emissive:0x0a3a66});
const R=new T.Group();sc.add(R);
// head: helmet, audio fins, horns, face mask
const H=new T.Group();R.add(H);
add(H,box(1.15,1,1,blue,1));add(H,box(.35,.3,.6,silver),0,.62,-.05);
[-1,1].forEach(s=>{add(H,box(.14,.6,.5,silver),s*.66,0,0);add(H,box(.15,.16,.5,red),s*.66,.36,0);add(H,cyl(.05,.07,.5,silver),s*.36,.7,-.1).rotation.z=-s*.25});
add(H,box(.95,.28,.1,dark),0,.1,.51);
const eyeL=add(H,box(.25,.12,.05,accM),-.24,.1,.58),eyeR=add(H,box(.25,.12,.05,accM),.24,.1,.58);
add(H,box(.68,.42,.14,silver,1),0,-.27,.5);const mouth=add(H,box(.34,.05,.04,accM),0,-.3,.59);
// torso: red chest with opening windshield panels and glowing spark core
const TO=add(R,new T.Group(),0,1.55,0);add(TO,box(1.9,1.3,1.05,red,1));
const core=add(TO,sph(.2,accM),0,.2,.45);add(TO,new T.Mesh(new T.TorusGeometry(.32,.05,10,36),accM),0,.2,.52);add(TO,box(1.3,.12,.1,silver),0,-.3,.56);
const flaps=[-1,1].map(s=>{const P=add(TO,new T.Group(),s*.5,.62,.53);add(P,box(.8,.62,.08,glass),0,-.32,0);return P});
add(R,box(1.2,.55,.8,blue,1),0,.62,0);add(R,box(1.55,.35,.85,silver,1),0,.22,0);add(R,cyl(.28,.32,.35,dark),0,2.35,0);
// arms: big shoulder armor, exhaust stacks, forearm cannons
const arm=s=>{const P=add(R,new T.Group(),s*1.35,2,0);add(P,box(.75,.65,.75,blue,1),s*.05,.1,0);add(P,cyl(.2,.17,.9,red),0,-.55,0);add(P,cyl(.09,.09,.9,silver),s*.35,.6,-.35);
 const F=add(P,new T.Group(),0,-1,0);add(F,sph(.19,accM));add(F,box(.5,.85,.5,blue,1),0,-.5,0);
 const gun=add(F,cyl(.09,.09,1,dark),0,-.55,.4);gun.rotation.x=Math.PI/2;gun.scale.y=.01;add(F,box(.34,.3,.28,silver),0,-1.05,0);add(F,cyl(.14,.14,.05,accM),0,-1.24,0);return{P,F,gun}};
const AL=arm(-1),AR=arm(1);
const blade=add(AR.F,box(.1,1.6,.05,accM),0,-1.9,0);blade.scale.y=.01;
const dome=new T.Mesh(new T.SphereGeometry(2.1,24,16),new T.MeshBasicMaterial({color:acc,transparent:true,opacity:.18}));dome.position.y=1.2;dome.visible=false;R.add(dome);
// legs: thigh, knee guard, calf with wheel, foot
const leg=s=>{const L=add(R,new T.Group(),s*.5,.1,0);add(L,box(.5,.95,.55,blue,1),0,-.5,0);const K=add(L,new T.Group(),0,-1,0);
 add(K,sph(.2,accM));add(K,box(.52,.3,.3,silver),0,0,.28);add(K,box(.55,.95,.65,red,1),0,-.5,-.02);add(K,cyl(.32,.32,.16,dark),s*.38,-.75,0).rotation.z=Math.PI/2;add(K,box(.62,.2,.95,silver,1),0,-1.05,.2);return{L,K}};
const LG=[leg(-1),leg(1)];
const ring=new T.Mesh(new T.TorusGeometry(1.6,.02,8,64),new T.MeshBasicMaterial({color:acc}));ring.rotation.x=Math.PI/2;ring.position.y=-2.05;sc.add(ring);
const shock=new T.Mesh(new T.TorusGeometry(1,.05,8,48),new T.MeshBasicMaterial({color:acc,transparent:true,opacity:0}));shock.rotation.x=Math.PI/2;shock.position.y=-2.05;sc.add(shock);
const beamM=new T.Mesh(new T.CylinderGeometry(.14,.14,8,12),new T.MeshBasicMaterial({color:acc,transparent:true,opacity:.85}));beamM.rotation.x=Math.PI/2;beamM.position.set(0,1.75,4.6);beamM.visible=false;R.add(beamM);
const flames=[-1,1].map(q=>{const m=new T.Mesh(new T.ConeGeometry(.25,.9,12),new T.MeshBasicMaterial({color:0xff9a1a}));m.rotation.x=Math.PI;m.position.set(q*.5,-2.45,.15);m.visible=false;R.add(m);return m});
const scan=new T.Mesh(new T.TorusGeometry(1.5,.03,8,48),new T.MeshBasicMaterial({color:acc,transparent:true,opacity:0}));scan.rotation.x=Math.PI/2;sc.add(scan);
// emotion table: eyeX,eyeY,tilt,mouthX,mouthY,mouthPos,bounce
const EM={neutral:[1,1,0,1,1,-.3,0],happy:[1.1,.55,0,1.5,1.6,-.28,.05],excited:[1.1,.6,0,1.6,2.2,-.28,.12],sad:[.85,.8,.35,.6,.8,-.36,0],stress:[.9,.85,.25,.7,.9,-.34,0],angry:[1,.6,-.4,1,.8,-.32,0],surprised:[.9,1.7,0,.5,3,-.32,.04],thinking:[.9,.9,0,.5,.8,-.3,0]};
const DUR={wave:2.4,nod:2.4,shake:2.4,dance:4,punch:1.2,kick:1,slash:1.3,blast:1.8,shield:3,jump:1,roar:2.4,uppercut:1.2,roundhouse:1.3,dodge:1,flip:1.4,slam:1.6,fly:4,beam:2.6,combo:2,salute:2,victory:2.6,charge:2.6,stance:3};
let slamHit=false,flipWas=false,shockT=-1,flash=0,roarK=0,emo="neutral",emoT=0,gest=null,gT=0,yaw=0,vel=0,drag=false,px=0,hx=0,hy=0,blink=0,nextBlink=2,dep=0;
const cur={ex:1,ey:1,tl:0,mx:1,my:1,mp:-.3,b:0};
impl.emo=(e,hold=6000)=>{emo=EM[e]?e:"neutral";clearTimeout(emoT);if(emo!=="neutral")emoT=setTimeout(()=>emo="neutral",hold)};
impl.gest=n=>{gest=n;gT=0;slamHit=false;if(n==="blast"||n==="roar"||n==="charge")flash=1};impl.reset=()=>{dep=0};
cv.addEventListener("pointerdown",e=>{drag=true;px=e.clientX;cv.setPointerCapture(e.pointerId);cv.style.cursor="grabbing"});
cv.addEventListener("pointermove",e=>{const r=cv.getBoundingClientRect();hx=((e.clientX-r.left)/r.width-.5)*2;hy=((e.clientY-r.top)/r.height-.5)*2;if(drag){vel=(e.clientX-px)*.012;yaw+=vel;px=e.clientX}});
const up=()=>{drag=false;cv.style.cursor="grab"};cv.addEventListener("pointerup",up);cv.addEventListener("pointercancel",up);
const turn=document.getElementById("avatarTurntable"),L=(a,b,k)=>a+(b-a)*k;let last=performance.now();
function frame(now){requestAnimationFrame(frame);const dt=Math.min((now-last)/1000,.05);last=now;
 if(!screen.classList.contains("visible"))return;
 const w=stage.clientWidth,h=stage.clientHeight,pr=ren.getPixelRatio();if(cv.width!==Math.floor(w*pr)||cv.height!==Math.floor(h*pr)){ren.setSize(w,h,false);cam.aspect=w/h;cam.updateProjectionMatrix()}
 const t=now/1000,mode=screen.dataset.mode||"normal",speak=typeof isSpeaking!=="undefined"&&isSpeaking,think=screen.classList.contains("is-thinking");
 acc.lerp(new T.Color(COL[mode]||COL.normal),.12);glow.color.copy(acc);
 if(!drag){yaw+=vel;vel*=.92}if(turn&&turn.classList.contains("auto-spin"))yaw+=dt*(Math.PI*2/4.2);
 R.rotation.y=yaw+(gest==="dance"?Math.sin(t*5)*.4:0);
 dep=Math.min(1,dep+dt/1.8);const e1=dep*dep*(3-2*dep);   // transform progress 0..1
 const E=EM[emo];["ex","ey","tl","mx","my","mp","b"].forEach((k,i)=>cur[k]=L(cur[k],E[i],.15));
 blink-=dt;if(t>nextBlink){blink=.12;nextBlink=t+2+Math.random()*3}
 const by=blink>0?.08:1;eyeL.scale.set(cur.ex,cur.ey*by,1);eyeR.scale.set(cur.ex,cur.ey*by,1);eyeL.rotation.z=cur.tl;eyeR.rotation.z=-cur.tl;
 mouth.scale.set(cur.mx,speak?.4+Math.abs(Math.sin(t*14))*2.2:cur.my+roarK*4,1);mouth.position.y=cur.mp;
 flash*=.92;glow.intensity=1.6+flash*6;accM.emissiveIntensity=(think?1+Math.abs(Math.sin(t*6)):1.4+Math.sin(t*2)*.2)+flash*3;
 let bob=Math.sin(t*1.6)*.04+Math.abs(Math.sin(t*8))*cur.b,hY=hx*.5,hX=hy*.25,aRz=.12,aLz=-.12,aRx=-.25;
 if(mode==="danger")hY+=Math.sin(t*12)*.08;
 if(mode==="fighting"){aRz=.5+Math.sin(t*9)*.3;aLz=-.5-Math.cos(t*9)*.3;aRx=-1}
 core.scale.setScalar(mode==="power"?1+Math.sin(t*5)*.18:1);
 scan.material.opacity=mode==="scanning"?.8:0;scan.position.y=-1.9+((t*.9)%1)*5.6;
 let dance=0,pRR=0,pRL=0,lean=0,kick=0,bl=0,sh=false,fire=false,jumpK=0,spin=0,flip=0,side=0,tilt=0,kickL=0,flame=false,beamOn=false,shk=0,aLx=-.25;
 if(gest){gT+=dt;const p=gT,pu=(a,b)=>Math.sin(Math.max(0,Math.min(1,(p-a)/(b-a)))*Math.PI);
  if(gest==="wave"){aRz=2.4+Math.sin(p*10)*.25;aRx=0}
  if(gest==="nod")hX=Math.sin(p*7)*.3;
  if(gest==="shake")hY=Math.sin(p*9)*.5;
  if(gest==="dance"){dance=Math.sin(p*5);bob+=Math.abs(dance)*.25;aRz=1.6+dance*.8;aLz=-1.6-Math.cos(p*5)*.8}
  if(gest==="punch"){pRR=-1.6*pu(0,.5);pRL=-1.6*pu(.5,1);aRx=-.2;lean=.25*(pu(0,.5)+pu(.5,1))}
  if(gest==="kick"){kick=-1.5*pu(.1,.9);lean=-.2*pu(.1,.9)}
  if(gest==="slash"){bl=1;pRR=L(-2.6,-.3,Math.min(p/.5,1));aRz=.3;lean=.2*pu(.2,.8)}
  if(gest==="blast"){pRR=pRL=-1.4;fire=true;lean=-.12*pu(.5,1);flash=Math.max(flash,pu(.4,.9))}
  if(gest==="shield"){pRR=pRL=-1.2;aRz=-.7;aLz=.7;sh=true}
  if(gest==="jump")jumpK=pu(0,.9);
  if(gest==="roar"){hX=-.55;aRz=1.1;aLz=-1.1}
  const ez=x=>x*x*(3-2*x),n01=(a,b)=>Math.max(0,Math.min(1,(p-a)/(b-a)));
  if(gest==="uppercut"){pRR=-2.5*pu(.1,.7);lean=.22*pu(.1,.7);jumpK=.25*pu(.2,.8)}
  if(gest==="roundhouse"){spin=Math.PI*2*ez(n01(0,1));kick=-1.5*pu(.15,.95);lean=-.15}
  if(gest==="dodge"){side=-1.3*pu(0,.9);tilt=-.4*pu(0,.9);hY=.6}
  if(gest==="flip"){flip=-Math.PI*2*ez(n01(0,1.1));jumpK=1.3*pu(0,1.2);kick=.8*pu(.2,.9);kickL=.8*pu(.2,.9)}
  if(gest==="slam"){jumpK=1.3*pu(0,.55);if(p<.35){aRz=2.7;aLz=-2.7}else{pRR=pRL=-1.4}if(p>=.5&&!slamHit){slamHit=true;shockT=0;flash=1}}
  if(gest==="fly"){const k=ez(n01(0,.6))*(1-ez(n01(3.4,4)));bob+=1.4*k+Math.sin(p*3)*.08*k;lean=1.1*k;pRR=pRL=.6*k;kick=.5*k;kickL=.5*k;flame=k>.2;spin=-.6*k}
  if(gest==="beam"){beamOn=true;spin=-.6;pRR=-1.3;aRx=-.2;flash=Math.max(flash,.5)}
  if(gest==="combo"){pRR=-1.6*pu(0,.4);pRL=-1.6*pu(.4,.8);lean=.2*(pu(0,.4)+pu(.4,.8));if(p>.8){spin=Math.PI*2*ez(n01(.8,1.7));kick=-1.5*pu(.9,1.7)}}
  if(gest==="salute"){pRR=-1.9;aRx=-2.6;hX=.15}
  if(gest==="victory"){aRz=2.8;aLz=-2.8;bob+=Math.abs(Math.sin(p*6))*.2;flash=Math.max(flash,.3)}
  if(gest==="charge"){aRz=.8;aLz=-.8;shk=.05;flash=Math.max(flash,.5+.4*Math.sin(p*14));bob-=.15}
  if(gest==="stance"){pRR=pRL=-1.1;aRx=-1.9;aLx=-1.9;lean=.1;bob+=Math.abs(Math.sin(p*7))*.04}
  if(p>(DUR[gest]||2.4))gest=null}
 roarK=gest==="roar"?.6+.4*Math.sin(t*20):0;
 // transform pose blends with live pose
 R.scale.setScalar(.8+.2*e1);H.position.y=L(2.2,3.05,e1);
 const fl=-Math.sin(e1*Math.PI)*1.1-(mode==="power"?.9+Math.sin(t*4)*.2:0);flaps.forEach(f=>f.rotation.x=fl);
 const shoot=((mode==="fighting"||mode==="danger")&&e1>.9)||fire;AL.gun.scale.y=AR.gun.scale.y=L(AR.gun.scale.y,shoot?1.6:.01,.15);
 H.rotation.y=L(H.rotation.y,hY,.1);H.rotation.x=L(H.rotation.x,hX,.1);
 AR.P.rotation.z=L(AR.P.rotation.z,aRz*e1,.2);AL.P.rotation.z=L(AL.P.rotation.z,aLz*e1,.2);
 AR.F.rotation.x=L(AR.F.rotation.x,L(-2.2,aRx,e1),.2);AL.F.rotation.x=L(AL.F.rotation.x,L(-2.2,aLx,e1),.2);
 LG.forEach((g,i)=>{g.L.rotation.x=L(-1.2,0,e1)+dance*.3*(i?-1:1)+(i?kick:kickL)-jumpK*.5;g.K.rotation.x=L(1.8,0,e1)+jumpK*1.1});
 if(flip){R.rotation.x=flip;flipWas=true}else{if(flipWas){R.rotation.x=0;flipWas=false}R.rotation.x=L(R.rotation.x,lean,.2)}
 R.rotation.z=(gest==="roar"?Math.sin(t*40)*.03:0)+tilt+(shk?Math.sin(t*60)*shk*.3:0);R.rotation.y+=spin;
 beamM.visible=beamOn;if(beamOn)beamM.material.opacity=.6+.3*Math.sin(t*40);flames.forEach(f=>{f.visible=flame;if(flame)f.scale.set(1,.7+Math.random()*.6,1)});
 if(shockT>=0){shockT+=dt;const q=1+shockT*3.2;shock.scale.set(q,q,q);shock.material.opacity=Math.max(0,.9-shockT*1.1);if(shockT>.9){shockT=-1;shock.material.opacity=0}}
 AR.P.rotation.x=L(AR.P.rotation.x,pRR,.3);AL.P.rotation.x=L(AL.P.rotation.x,pRL,.3);
 blade.scale.y=L(blade.scale.y,bl?1:.01,.25);dome.visible=sh;if(sh){dome.material.opacity=.15+Math.sin(t*8)*.05;dome.rotation.y=t}
 R.position.x=side+(shk?(Math.random()-.5)*shk:0)+(mode==="virus"&&Math.random()>.85?(Math.random()-.5)*.12:0);
 R.position.y=-.4+bob+jumpK*1.4;ren.render(sc,cam)}
requestAnimationFrame(frame);
}})();

/* ===== ALEX PLUS: JARVIS HUD alerts + device health ===== */

/* =========================================================
   ALEX JARVIS - TONY STARK STYLE AVATAR
   HUD • SYSTEM MONITOR • ALERTS • SUIT COMMANDS
   FIXED: API URL • HEALTH CHECK • SAFE FUNCTION ACCESS
========================================================= */

(() => {
"use strict";

/* ---------------- CONFIGURATION ---------------- */

// API_URL comes from script.js

const screen = document.getElementById("avatarScreen");
const stage = document.querySelector(".avatar-stage");

if (!screen || !stage) {
    console.warn("ALEX: Avatar screen or stage not found.");
    return;
}

const A = () => window.ALEXAvatar3D;

const isOpen = () => screen.classList.contains("visible");

const J = {
    bat: null,
    sys: null,
    server: false,
    down: false,
    checking: false,
    t: {},
    previousMode: "normal"
};

/* ---------------- SAFE HELPERS ---------------- */

const cool = (key, ms) => {
    const now = Date.now();

    if (J.t[key] && now - J.t[key] < ms) {
        return false;
    }

    J.t[key] = now;
    return true;
};

const number = value => {
    const n = Number(value);
    return Number.isFinite(n) ? Math.round(n) : "--";
};

const getGlobalFunction = name => {
    return typeof window[name] === "function"
        ? window[name]
        : null;
};

function callGlobal(name, ...args) {
    const fn = getGlobalFunction(name);

    if (!fn) {
        console.warn("ALEX: Function unavailable:", name);
        return undefined;
    }

    try {
        return fn(...args);
    } catch (error) {
        console.error("ALEX function error:", name, error);
        return undefined;
    }
}

function isAuthenticated() {
    return typeof authenticated !== "undefined" && authenticated === true;
}

async function backendRequest(path) {
    const response = await fetch(API_URL + path, {
        method: "GET",
        credentials: "include",
        headers: {
            "Accept": "application/json"
        }
    });

    if (!response.ok) {
        throw new Error(
            "Backend HTTP " + response.status
        );
    }

    return await response.json();
}

/* ---------------- HUD DESIGN ---------------- */

const style = document.createElement("style");

style.textContent = `
.jv-hud {
    position:absolute;
    top:14px;
    left:16px;
    z-index:3;
    pointer-events:none;
    font:11px/1.7 monospace;
    letter-spacing:1px;
    color:var(--mode,#00eaff);
    text-shadow:0 0 8px currentColor;
    white-space:pre;
    opacity:.9;
}

@media(max-width:520px) {
    .jv-hud {
        font-size:9px;
        top:8px;
        left:8px;
    }
}
`;

document.head.appendChild(style);

const hud = document.createElement("div");
hud.className = "jv-hud";
stage.appendChild(hud);

/* ---------------- BATTERY ---------------- */

if (navigator.getBattery) {
    navigator.getBattery()
        .then(battery => {
            J.bat = battery;

            battery.addEventListener("levelchange", paint);
            battery.addEventListener("chargingchange", paint);

            paint();
        })
        .catch(error => {
            console.warn("ALEX battery access unavailable:", error);
        });
}

/* ---------------- HUD UPDATE ---------------- */

function paint() {
    if (!isOpen()) return;

    const battery = J.bat;
    const system = J.sys || {};

    const batteryText = battery
        ? number(battery.level * 100) +
          "%" +
          (battery.charging ? " +" : "")
        : "--";

    hud.textContent = [
        "J.A.R.V.I.S  ONLINE",
        "MODE  " + (screen.dataset.mode || "normal").toUpperCase(),
        "NET   " + (navigator.onLine ? "ONLINE" : "OFFLINE"),
        "SRV   " + (J.server ? "OK" : "DOWN"),
        "DEV   " + batteryText,
        "PC    CPU " + number(system.cpu_percent) +
        "  RAM " + number(system.memory_percent),
        "TIME  " + new Date().toLocaleTimeString("en-IN")
    ].join("\n");
}

setInterval(paint, 1000);

/* ---------------- SYSTEM INFORMATION ---------------- */

async function sys() {
    if (!isAuthenticated()) return null;

    if (J.checking) return J.sys;

    J.checking = true;

    try {
        const data = await backendRequest("/plus/health");

        J.sys = data;
        J.server = true;

        return data;

    } catch (error) {
        console.warn("ALEX system information error:", error);
        return null;

    } finally {
        J.checking = false;
        paint();
    }
}

setInterval(() => {
    if (isAuthenticated()) sys();
}, 30000);

setTimeout(() => {
    if (isAuthenticated()) sys();
}, 3000);

/* ---------------- VOICE ---------------- */

function speak(message) {
    try {
        const speakFunction = getGlobalFunction("speakText");

        if (J.server && isAuthenticated() && speakFunction) {
            speakFunction(message);
            return;
        }
    } catch (error) {
        console.warn("ALEX backend voice unavailable:", error);
    }

    try {
        if ("speechSynthesis" in window) {
            window.speechSynthesis.cancel();

            const utterance = new SpeechSynthesisUtterance(message);
            utterance.lang = "hi-IN";

            window.speechSynthesis.speak(utterance);
        }
    } catch (error) {
        console.warn("ALEX local voice unavailable:", error);
    }
}

/* ---------------- AVATAR MODE ---------------- */

function setMode(mode) {
    callGlobal("setAvatarMode", mode);
}

function showAvatarSafely() {
    if (!isOpen()) {
        callGlobal("showAvatar");
    }
}

/* ---------------- ALERT SYSTEM ---------------- */

function alertJ(message, critical = false) {
    callGlobal("addMessage", "assistant", "ALERT: " + message);

    if (critical) {
        J.previousMode = screen.dataset.mode || "normal";

        showAvatarSafely();
        setMode("danger");

        setTimeout(() => {
            setMode(
                J.previousMode === "danger"
                    ? "normal"
                    : J.previousMode
            );
        }, 9000);
    }

    speak(message);
}

/* ---------------- SYSTEM MONITOR ---------------- */

async function watch() {

    const conn = navigator.connection;
    if (conn && ["slow-2g", "2g"].includes(conn.effectiveType) && cool("net2g", 900000)) {
        alertJ("Sir, network bahut kamzor hai. Internet slow chal raha hai.");
    }

    const battery = J.bat;

    if (battery && !battery.charging) {
        const percentage = Math.round(battery.level * 100);

        if (percentage <= 10 && cool("b10", 600000)) {
            alertJ(
                `Sir, device battery sirf ${percentage} percent hai. Turant charger lagayein.`,
                true
            );

        } else if (
            percentage <= 20 &&
            cool("b20", 900000)
        ) {
            alertJ(
                `Sir, battery ${percentage} percent hai. Charger ready rakhein.`
            );
        }
    }

    const system = J.sys;

    if (system) {

        if (
            Number(system.cpu_percent) > 92 &&
            cool("cpu", 300000)
        ) {
            alertJ(
                `Sir, PC ka CPU ${number(system.cpu_percent)} percent par hai. Kuch heavy chal raha hai.`
            );
        }

        if (
            Number(system.memory_percent) > 93 &&
            cool("ram", 300000)
        ) {
            alertJ(
                `Sir, PC ki memory ${number(system.memory_percent)} percent bhar gayi hai.`
            );
        }

        if (
            Number(system.disk_percent) > 95 &&
            cool("disk", 3600000)
        ) {
            alertJ(
                `Sir, PC ki disk ${number(system.disk_percent)} percent full hai.`
            );
        }

        if (Number(system.temp_c) > 85 && cool("temp", 600000)) {
            alertJ(`Sir, PC ka temperature ${number(system.temp_c)} degree ho gaya hai. Overheat ho sakta hai, kuch heavy band karein.`, true);
        }

        if (
            system.battery_percent != null &&
            !system.battery_plugged &&
            Number(system.battery_percent) <= 10 &&
            cool("pcb", 600000)
        ) {
            alertJ(
                `Sir, PC battery ${number(system.battery_percent)} percent hai. Charger lagayein.`,
                true
            );
        }
    }

    /* REAL BACKEND HEALTH CHECK */

    try {
        const response = await fetch(API_URL + "/health", {
            method: "GET",
            credentials: "include",
            headers: {
                "Accept": "application/json"
            }
        });

        if (!response.ok) {
            throw new Error("HTTP " + response.status);
        }

        const data = await response.json();

        if (!data || data.status !== "running") {
            throw new Error("Backend health check failed");
        }

        J.server = true;

        if (J.down) {
            J.down = false;
            alertJ("Sir, server wapas online hai.");
        }

    } catch (error) {

        J.server = false;

        if (!J.down) {
            J.down = true;

            alertJ(
                "Sir, backend server offline ho gaya hai. Mera dimaag abhi connect nahi hai."
            );
        }
    }

    paint();
}

/* ---------------- NETWORK EVENTS ---------------- */

window.addEventListener("offline", () => {
    alertJ("Sir, internet connection toot gaya hai.", true);
});

window.addEventListener("online", () => {
    alertJ("Sir, internet wapas aa gaya.");
});

/* ---------------- MONITOR START ---------------- */

setInterval(watch, 15000);

setTimeout(watch, 5000);

/* ---------------- STATUS REPORT ---------------- */

function report() {

    const battery = J.bat;
    const system = J.sys;
    const problems = [];

    const parts = [];

    parts.push(
        "Sir, abhi " +
        new Date().toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit"
        }) +
        " baje hain."
    );

    parts.push(
        navigator.onLine
            ? "Internet connected hai."
            : "Internet band hai."
    );

    if (!navigator.onLine) {
        problems.push("Internet offline");
    }

    if (battery) {

        const percentage = Math.round(battery.level * 100);

        parts.push(
            `Device battery ${percentage} percent` +
            (battery.charging ? ", charging par." : ".")
        );

        if (percentage <= 20 && !battery.charging) {
            problems.push("Device battery low");
        }
    }

    if (system && system.cpu_percent != null) {

        parts.push(
            `PC par CPU ${number(system.cpu_percent)}, memory ${number(system.memory_percent)}, disk ${number(system.disk_percent)} percent.`
        );

        if (Number(system.cpu_percent) > 92) {
            problems.push("CPU usage high");
        }

        if (Number(system.memory_percent) > 93) {
            problems.push("Memory usage high");
        }

        if (Number(system.disk_percent) > 95) {
            problems.push("Disk almost full");
        }
    }

    if (!J.server) {
        problems.push("Backend offline");
    }

    parts.push(
        problems.length
            ? "Kuch cheezein dhyan maangti hain, Sir."
            : "Sab kuch normal hai, Sir. In checks mein koi khatra nahi mila."
    );

    return parts.join(" ");
}

/* ---------------- JARVIS COMMANDS ---------------- */

window.ALEXJarvis = {

    async handle(t, full, say) {

        t = String(t || "").toLowerCase();
        full = String(full || "").toLowerCase();

        if (typeof say !== "function") {
            say = speak;
        }

        /* WAKE WORD */

        if (/^(hey |ok )?jarvis$/.test(full)) {
            say("At your service, Sir.");
            return true;
        }

        /* STATUS REPORT */

        if (
            /\b(status report|system status|system check|diagnostic\w*|status batao|sab theek hai|report do)\b/.test(t)
        ) {
            await sys();
            say(report());
            return true;
        }

        /* SECURITY SCAN */

        if (
            /\b(threat scan|security scan|sab scan|full scan)\b/.test(t)
        ) {
            showAvatarSafely();
            setMode("scanning");

            await sys();

            setTimeout(() => {
                say("Scan complete. " + report());
            }, 1800);

            return true;
        }

        /* SUIT ON */

        if (
            /\b(suit up|armor on|armour on|suit on|iron man mode)\b/.test(t)
        ) {
            showAvatarSafely();
            setMode("power");

            try {
                A()?.transform?.();
            } catch (error) {
                console.warn("ALEX suit animation error:", error);
            }

            setTimeout(() => {
                say("Suit up, Sir. Saare systems online. Repulsors ready.");
            }, 700);

            return true;
        }

        /* SUIT OFF */

        if (
            /\b(suit off|armor off|armour off|stand down)\b/.test(t)
        ) {
            setMode("normal");
            say("Standing down, Sir.");
            return true;
        }

        /* MORNING BRIEFING */

        if (
            /\b(briefing|good morning|morning update)\b/.test(t)
        ) {
            await sys();

            let newsText = "";

            try {
                if (isAuthenticated()) {
                    const response = await fetch(
                        API_URL + "/plus/news?topic=india&limit=3",
                        {
                            credentials: "include",
                            headers: {
                                "Accept": "application/json"
                            }
                        }
                    );

                    if (!response.ok) {
                        throw new Error("News HTTP " + response.status);
                    }

                    const data = await response.json();

                    if (Array.isArray(data.items)) {
                        newsText = " Top khabrein: " +
                            data.items
                                .map(item => item.title)
                                .filter(Boolean)
                                .join(". ") +
                            ".";
                    }
                }
            } catch (error) {
                console.warn("ALEX news unavailable:", error);
            }

            say("Good morning, Sir. " + report() + newsText);

            return true;
        }

        return false;
    }
};

console.log("ALEX JARVIS Avatar module loaded successfully.");

})();

/* ===== ALEX PLUS: builder, camera eyes, awareness, voice recognition ===== */
/* ALEX PLUS 2: build projects, camera eyes, awareness, voice recognition, lovely voice */
(()=>{
const sleep=ms=>new Promise(r=>setTimeout(r,ms));
const fem=()=>typeof selectedVoice!=="undefined"&&selectedVoice==="female";
const g=(m,f)=>fem()?f:m;
const ls={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
const chat=document.getElementById("chatMessages");
function addLink(text,href){if(!chat)return;const d=document.createElement("div");d.style.cssText="margin:8px 0;padding:10px 12px;border:1px solid #00eaff66;border-radius:10px";
 const a=document.createElement("a");a.href=href;a.textContent=text;a.setAttribute("download","");a.style.color="#00eaff";d.appendChild(a);chat.appendChild(d);chat.scrollTop=chat.scrollHeight}
// ---------- lovely voice preference (female by default) ----------
const btn=id=>document.getElementById(id);
["voiceFemale","voiceMale"].forEach(id=>btn(id)?.addEventListener("click",()=>ls.set("alexVoice",id==="voiceFemale"?"female":"male")));
const vt=setInterval(()=>{if(typeof authenticated!=="undefined"&&authenticated){clearInterval(vt);const p=ls.get("alexVoice")||"female";ls.set("alexVoice",p);
 if(typeof selectedVoice!=="undefined"&&selectedVoice!==p)btn(p==="female"?"voiceFemale":"voiceMale")?.click()}},800);setTimeout(()=>clearInterval(vt),60000);
// ---------- project builder ----------
const BUILD=/\b(bana\w*|build|create|make|develop)\b.*\b(app|website|web ?site|site|game|project|script|bot|tool|calculator|page|program|software|api|todo|portfolio|landing)\b|\b(app|website|web ?site|site|game|project|script|bot|tool|calculator|page|program|software|api|todo|portfolio|landing)\b.*\b(bana\w*|build|create|make|develop)\b/;
const CONT=/\b(complete|continue|finish|aage badha\w*|poora|improve)\b.*\b(project|app|website|game)\b|\b(project|app|website|game)\b.*\b(complete|continue|finish|aage badha\w*|poora|improve)\b/;
const ASKQ=/\b(kaise|how to|how do|how can|kyun|why|tarika|sikha\w*|explain|samjha\w*|idea)\b/;
async function build(msg,cont){
 const say=window.__alexSay;say(g("Theek hai, abhi banata hoon. Thoda time lagega.","Theek hai, abhi banati hoon. Thoda time lagega."));
 try{if(cont==="latest"){const l=await apiRequest("/plus/projects");cont=(l.projects||[])[0];if(!cont){say("Abhi tak koi project nahi bana. Pehle bolo kya banana hai.");return true}}
  const r=await apiRequest("/plus/build",{method:"POST",body:JSON.stringify({request:msg,continue:cont||""})});
  addMessage("assistant",`${r.summary}\nFiles: ${r.files.join(", ")}\nRun: ${r.run}`);addLink("Download "+r.name+".zip",API_URL+r.download);
  say(g("Project taiyaar hai. Download link chat mein hai.","Project taiyaar hai. Download link chat mein hai."))
 }catch(e){say("Project nahi ban paaya: "+(e.message||e))}return true}
// ---------- camera eyes ----------
const LOOK=/\b(what do you see|samne kya|kya dikh\w*|camera (se )?(dekho|dekh)|ye kya hai|yeh kya hai|is(ko|e) pehchan\w*|pehchan\w* (ye|yeh|isko|ise)|identify (this|it)|what is this|read this|ye padho|isko padho|ye kaun hai|yeh kaun hai)\b/;
const EYES="You are the eyes of a personal AI. Look carefully and answer in simple Hinglish like a friend: name the main objects, read any visible text, say how many people there are and what they seem to be doing, and mention anything unusual or unsafe. Be specific, max 5 sentences. Never guess who a real person is from their face.";
async function see(question,say){
 let img=typeof captureCameraImage==="function"?captureCameraImage():null;
 if(!img&&typeof startCamera==="function"){if(!await startCamera()){say("Camera start nahi ho paaya. Permission check karo.");return null}await sleep(900);img=captureCameraImage()}
 if(!img){say("Camera se tasveer nahi mil paayi.");return null}
 const r=await apiRequest("/vision",{method:"POST",body:JSON.stringify({image:img,question})});
 return r.response||r.description||r.answer||r.message||"Samajh nahi aaya."}
async function look(msg,say){say(g("Dekh raha hoon...","Dekh rahi hoon..."));try{const a=await see(msg+"\n"+EYES,say);if(a)say(a)}catch(e){say("Vision error: "+(e.message||e))}return true}
// ---------- awareness: watches the camera and speaks when something changes ----------
let awT=null,prev=null,lastSpoke=0;
function tiny(){const v=btn("cameraVideo");if(!v||!v.videoWidth)return null;const c=document.createElement("canvas");c.width=32;c.height=24;const x=c.getContext("2d");x.drawImage(v,0,0,32,24);return x.getImageData(0,0,32,24).data}
async function aware(on,say){clearInterval(awT);awT=null;prev=null;
 if(!on){say("Awareness band kar diya.");return}
 if(typeof startCamera==="function"&&!tiny()){if(!await startCamera()){say("Camera start nahi ho paaya.");return}await sleep(1200)}
 say(g("Awareness on hai. Main camera par nazar rakhunga, kuch badle to bata dunga.","Awareness on hai. Main camera par nazar rakhungi, kuch badle to bata dungi."));
 awT=setInterval(async()=>{const d=tiny();if(!d)return;if(prev){let s=0;for(let i=0;i<d.length;i+=4)s+=Math.abs(d[i]-prev[i]);const diff=s/(d.length/4);
  if(diff>14&&Date.now()-lastSpoke>45000){lastSpoke=Date.now();try{const a=await see("In ONE short Hinglish sentence say what changed or who or what just appeared. Mention anything unsafe. "+EYES,say);if(a)say(a)}catch(e){}}}prev=d},5000)}
// ---------- voice recognition (basic voiceprint, stored only on this device) ----------
const B=24;let ac,an,fb,tb,acc=new Float64Array(B),cnt=0,enr=null,stored=null;
try{stored=JSON.parse(ls.get("alexVoiceprint")||"null")}catch(e){}
async function micInit(){if(an)return;try{const st=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
 ac=new(window.AudioContext||window.webkitAudioContext)();an=ac.createAnalyser();an.fftSize=2048;ac.createMediaStreamSource(st).connect(an);fb=new Float32Array(an.frequencyBinCount);tb=new Float32Array(an.fftSize);setInterval(sample,50)}catch(e){console.warn("voiceprint mic off",e)}}
["pointerdown","keydown"].forEach(ev=>addEventListener(ev,micInit,{once:true}));
function sample(){if(typeof isSpeaking!=="undefined"&&isSpeaking)return;an.getFloatTimeDomainData(tb);let q=0;for(const v of tb)q+=v*v;if(Math.sqrt(q/tb.length)<.02)return;
 an.getFloatFrequencyData(fb);const bin=ac.sampleRate/an.fftSize,f=new Float64Array(B);
 for(let b=0;b<B;b++){const i0=Math.max(1,Math.floor(100*Math.pow(40,b/B)/bin)),i1=Math.max(i0+1,Math.floor(100*Math.pow(40,(b+1)/B)/bin));let s=0;for(let i=i0;i<i1;i++)s+=Math.pow(10,fb[i]/10);f[b]=10*Math.log10(s/(i1-i0)+1e-12)}
 for(let b=0;b<B;b++)acc[b]+=f[b];cnt++;if(enr)enr.push(f)}
const unit=v=>{const m=v.reduce((a,b)=>a+b,0)/v.length,c=Array.from(v,x=>x-m),n=Math.sqrt(c.reduce((a,b)=>a+b*b,0))||1;return c.map(x=>x/n)};
const mean=a=>{const o=new Float64Array(B);a.forEach(f=>f.forEach((x,i)=>o[i]+=x/a.length));return o};
const cos=(a,b)=>a.reduce((s,x,i)=>s+x*b[i],0);
function voiceCheck(){if(!stored||cnt<8){acc.fill(0);cnt=0;return null}const v=unit(Array.from(acc,x=>x/cnt));acc.fill(0);cnt=0;const sc=cos(v,stored.v);return{owner:sc>=stored.thr,score:sc}}
async function enroll(say){await micInit();if(!an){say("Mic nahi mil raha.");return true}
 say(g("Theek hai. Ab 8 second tak kuch bhi bolte rahiye, jaise apne din ke baare mein.","Theek hai. Ab 8 second tak kuch bhi bolte rahiye, jaise apne din ke baare mein."));
 await sleep(3800);window.__alexMute=true;enr=[];await sleep(8000);const frames=enr;enr=null;window.__alexMute=false;
 if(frames.length<40){say("Awaaz bahut kam aayi. Thoda zor se bolkar dobara try karo: meri awaaz yaad karo.");return true}
 const h=Math.floor(frames.length/2),a=unit(mean(frames.slice(0,h))),b=unit(mean(frames.slice(h))),self=cos(a,b);
 stored={v:unit(mean(frames)),thr:Math.max(.85,self-.06)};ls.set("alexVoiceprint",JSON.stringify(stored));acc.fill(0);cnt=0;
 say(g("Aapki awaaz yaad kar li. Ab jab aap bologe, main pehchaan lunga.","Aapki awaaz yaad kar li. Ab jab aap bologe, main pehchaan lungi."));return true}
// ---------- router (called from the main hook) ----------
window.ALEXPlus2={voiceCheck,async handle(t,msg,say){window.__alexSay=say;
 if(/\b(female|ladki|girl|lady)\b.*\b(voice|awaaz|awaz)\b|\b(voice|awaaz|awaz)\b.*\b(female|ladki|girl)\b/.test(t)){ls.set("alexVoice","female");btn("voiceFemale")?.click();setTimeout(()=>say("Ab main aapse meethi awaaz mein baat karungi."),700);return true}
 if(/\b(male|ladka|boy)\b.*\b(voice|awaaz|awaz)\b|\b(voice|awaaz|awaz)\b.*\b(male|ladka|boy)\b/.test(t)){ls.set("alexVoice","male");btn("voiceMale")?.click();setTimeout(()=>say("Ab main male awaaz mein baat karunga."),700);return true}
 if(/\b(meri awaaz|my voice)\b.*\b(yaad|pehchan\w*|learn|remember|enroll)\b/.test(t)){return enroll(say)}
 if(/\b(awaaz|voice)\b.*\b(bhool|forget|delete)\b/.test(t)){stored=null;ls.set("alexVoiceprint","");say("Aapki awaaz ka data hata diya.");return true}
 if(/\b(awareness|sab dekhte raho|nazar rakho)\b/.test(t)){await aware(!/\b(off|band|mat)\b/.test(t),say);return true}
 if(LOOK.test(t))return look(msg,say);
 if(ASKQ.test(t))return false;
 if(CONT.test(t)){const m=t.match(/project\s+([\w-]+)/);return build(msg,m&&!/^(complete|ko|ka)$/.test(m[1])?m[1]:"latest")}
 if(BUILD.test(t))return build(msg,"");
 return false}};
})();

/* ===== ALEX PLUS: danger auto-avatar, maps, listening, robot bridge, phone control ===== */
/* ALEX PLUS 3: danger auto-avatar, wake-word persona, stronger listening, maps, robot bridge, phone (APK) control */
(()=>{
const A=()=>window.ALEXAvatar3D,open=()=>document.getElementById("avatarScreen")?.classList.contains("visible");
const ls={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
const chat=document.getElementById("chatMessages");
const fem=()=>typeof selectedVoice!=="undefined"&&selectedVoice==="female";
function link(text,href){if(!chat)return;const d=document.createElement("div");d.style.cssText="margin:8px 0;padding:10px 12px;border:1px solid #ff344f88;border-radius:10px";
 const a=document.createElement("a");a.href=href;a.textContent=text;a.target="_blank";a.style.color="#00eaff";d.appendChild(a);chat.appendChild(d);chat.scrollTop=chat.scrollHeight}
const here=()=>new Promise(r=>navigator.geolocation?navigator.geolocation.getCurrentPosition(p=>r([p.coords.latitude,p.coords.longitude]),()=>r(null),{enableHighAccuracy:true,timeout:8000}):r(null));
// ---------- maps panel ----------
function mapPanel(src,href,title){let p=document.getElementById("alexMap");if(!p){p=document.createElement("div");p.id="alexMap";
 p.style.cssText="position:fixed;left:12px;bottom:12px;width:min(420px,92vw);height:300px;z-index:70;background:#020811;border:1px solid #00eaff88;border-radius:12px;overflow:hidden;box-shadow:0 0 24px #00eaff44";document.body.appendChild(p)}
 p.textContent="";const bar=document.createElement("div");bar.style.cssText="display:flex;justify-content:space-between;gap:12px;padding:6px 10px;font:12px monospace;color:#00eaff";
 const t=document.createElement("span");t.textContent=title;const a=document.createElement("a");a.href=href;a.target="_blank";a.textContent="OPEN MAPS";a.style.color="#00eaff";
 const x=document.createElement("span");x.textContent="X";x.style.cursor="pointer";x.onclick=()=>p.remove();bar.append(t,a,x);
 const f=document.createElement("iframe");f.src=src;f.style.cssText="width:100%;height:calc(100% - 30px);border:0";f.allow="geolocation";p.append(bar,f)}
const enc=encodeURIComponent,emb=q=>"https://maps.google.com/maps?q="+enc(q)+"&output=embed",sea=q=>"https://www.google.com/maps/search/?api=1&query="+enc(q);
const PLACE=/\b(hospital|police|petrol pump|petrol|atm|restaurant|medical|pharmacy|hotel|cafe|bank|school|mandir|temple|mall|bus stand|station|clinic|doctor)\b/;
const clean=s=>s.replace(/\b(show|me|the|to|dikhao|dikha|batao|bata|map|maps|google|open|ka|ki|ke|liye|tak|par|pe|on|please|do|karo|mujhe|kholo)\b/g," ").replace(/\s+/g," ").trim();
async function maps(t,say){
 if(/\b(meri location|my location|where am i|main kahan|mai kahan)\b/.test(t)){const p=await here();if(!p){say("Location nahi mili. Location permission check karo.");return true}
  mapPanel("https://maps.google.com/maps?q="+p[0]+","+p[1]+"&z=16&output=embed","https://www.google.com/maps?q="+p[0]+","+p[1],"MY LOCATION");say("Aap yahan hain. Map neeche khol diya.");return true}
 const pm=t.match(PLACE);
 if(pm&&/\b(nearby|nearest|near me|paas (ka|ki|ke|mein|me)|sabse paas)\b/.test(t)){const p=await here();const q=p?pm[1]+" near "+p[0]+","+p[1]:pm[1]+" near me";mapPanel(emb(q),sea(q),"NEARBY "+pm[1].toUpperCase());say(pm[1]+" ka map khol diya.");return true}
 let m=t.match(/(?:route|raasta|rasta|directions?|navigate|navigation)\s*(?:to|tak|ka|ke liye)?\s+(.+)/)||t.match(/(.+?)\s+(?:ka|ke liye|tak)?\s*(?:route|raasta|rasta|directions?)\b/)||t.match(/(.+?)\s+(?:jana hai|jaana hai|kaise jaun|kaise jau)\b/);
 if(m){const dest=clean(m[1]);if(dest){const p=await here();const src=p?"https://maps.google.com/maps?saddr="+p[0]+","+p[1]+"&daddr="+enc(dest)+"&output=embed":emb(dest);
  mapPanel(src,"https://www.google.com/maps/dir/?api=1&destination="+enc(dest),"ROUTE: "+dest.toUpperCase());say(dest+" ka raasta map par dikha diya.");return true}}
 if(/\b(map|maps|naksha)\b/.test(t)&&/\b(dikhao|dikha|show|kholo|open|par|pe|on)\b/.test(t)){const place=clean(t);if(!place||/^(map|maps)$/.test(place)){const p=await here();if(p){mapPanel("https://maps.google.com/maps?q="+p[0]+","+p[1]+"&z=15&output=embed","https://www.google.com/maps?q="+p[0]+","+p[1],"MAP");say("Map khol diya.");return true}return false}
  mapPanel(emb(place),sea(place),place.toUpperCase());say(place+" map par dikha diya.");return true}
 return false}
// ---------- danger: avatar switches on by itself ----------
const EMERG=/\b(bachao|bachaao|emergency)\b|\b(mujhe|mere liye|main)\b.*\b(khatra|danger|darr|dar lag\w*)\b|\b(khatra|danger)\s+(hai|ho gaya|lag raha|mehsoos)\b|\bkhatre mein\b|\b(koi|kuch)\b.*\b(pichha|peeche)\b.*\b(kar raha|aa raha|hai)\b|\bhelp (me|help)\b(?!.*\b(with|to)\b)|बचाओ|मदद करो|खतरा है|खतरे में|इमरजेंसी/i;
let lastE=0;
async function emergency(say){lastE=Date.now();if(!open())showAvatar();setAvatarMode("danger");A()?.gesture("shield");
 addMessage("assistant","THREAT PROTOCOL ACTIVE\nAgar jaan ko khatra hai to abhi 112 dial karein. Main aapke saath hoon.");
 link("Call 112 (Emergency)","tel:112");link("Ambulance 108","tel:108");link("Police 100","tel:100");
 setTimeout(()=>say("Sir, threat protocol on. Main aapke saath hoon. Agar jaan ko khatra hai to abhi ek ek ek dial karein. Mujhe batayein, kya hua?"),500);
 const p=await here();if(p){link("Meri location (Google Maps)","https://www.google.com/maps?q="+p[0]+","+p[1]);mapPanel(emb("police station near "+p[0]+","+p[1]),sea("police station near "+p[0]+","+p[1]),"NEAREST POLICE")}
 if(window.AlexNative)try{AlexNative.vibrate(600)}catch(e){}}
// ---------- stronger listening ----------
function upgradeListening(){if(typeof recognition==="undefined"||!recognition||recognition.__up)return;recognition.__up=true;recognition.maxAlternatives=5;
 const KEY=/(alex|jarvis|avatar|avtar|khatra|danger|bachao|emergency|suit|fighting|punch|kick|blast|shield|transform|status|route|banao|dekho|एलेक्स|जार्विस|अवतार)/i;
 recognition.onresult=async e=>{let fin="",live="";
  for(let i=e.resultIndex;i<e.results.length;i++){const r=e.results[i];
   if(r.isFinal){let best=r[0].transcript,bs=-1;for(let k=0;k<r.length;k++){const s=(KEY.test(r[k].transcript)?2:0)+(r[k].confidence||0);if(s>bs){bs=s;best=r[k].transcript}}fin+=best+" "}
   else live+=r[0].transcript}
  const shown=(live||fin).trim(),st=document.getElementById("listenStatus");if(st&&shown)st.textContent="SUN RAHA: "+shown.slice(0,36);
  if(shown&&EMERG.test(shown)&&Date.now()-lastE>12000)emergency(window.__alexSay||(t=>{try{addMessage("assistant",t);speakText(t)}catch(x){}}));
  fin=fin.trim();if(!fin)return;pauseRecognition();await processUserMessage(fin,"voice")};
 const sr=window.scheduleRecognitionRestart;if(typeof sr==="function")window.scheduleRecognitionRestart=d=>sr(Math.min(d,400))}
const lt=setInterval(upgradeListening,1000);setTimeout(()=>clearInterval(lt),120000);
// ---------- robot bridge: mirror every avatar action to a physical robot ----------
let robot=ls.get("alexRobotUrl")||"";
addEventListener("alex-action",e=>{if(!robot)return;try{fetch(robot,{method:"POST",mode:"no-cors",body:JSON.stringify({...e.detail,t:Date.now()})}).catch(()=>{})}catch(x){}});
// ---------- phone control (works inside the ALEX APK) ----------
let pend=null;
async function phone(t,msg,say){const N=window.AlexNative;if(!N)return false;
 if(pend&&Date.now()-pend.t<30000){if(/^(haan|han|yes|bhejo|send|ok|kar do|kardo)$/.test(t)){const p=pend;pend=null;say(N.sms(p.number,p.text)?"Message bhej diya.":"Message nahi ja paaya.");return true}
  if(/^(nahi|no|cancel|mat)$/.test(t)){pend=null;say("Theek hai, message cancel kar diya.");return true}}
 const contact=name=>{try{return JSON.parse(N.findContact(name))[0]||null}catch(e){return null}};
 if(/\b(call|phone|dial)\b/.test(t)&&!/\b(video|whatsapp)\b/.test(t)){const num=(msg.match(/\+?\d[\d\s-]{7,}\d/)||[])[0];let target=num?num.replace(/[\s-]/g,""):null,label=target;
  if(!target){const nm=t.replace(/\b(call|phone|dial|karo|kar do|kardo|lagao|laga do|ko|please|pls|mujhe|ek|a|to)\b/g," ").trim();if(!nm)return false;const c=contact(nm);if(!c){say(nm+" naam ka contact nahi mila.");return true}target=c.number;label=c.name}
  say(label+" ko call laga rahi hoon.".replace("rahi",fem()?"rahi":"raha"));setTimeout(()=>N.call(target),900);return true}
 let m=t.match(/sms\s+(?:bhejo|send|karo)\s+(.+?)\s+(?:ko|to)\s+(.+)/)||t.match(/(.+?)\s+ko\s+sms\s+(?:bhejo|karo)\s+(.+)/);
 if(m){const num=(m[1].match(/\+?\d[\d\s-]{7,}\d/)||[])[0],c=num?{name:num,number:num.replace(/[\s-]/g,"")}:contact(m[1].trim());if(!c){say(m[1]+" naam ka contact nahi mila.");return true}
  pend={number:c.number,text:m[2],t:Date.now()};say(c.name+" ko ye message bhejun: "+m[2]+". Haan bolein to bhej dungi.");return true}
 if(/\b(torch|flashlight|flash light)\b/.test(t)){const on=!/\b(off|band|bujha\w*)\b/.test(t);N.torch(on);say(on?"Torch on.":"Torch off.");return true}
 m=t.match(/\b(?:open|kholo|khol do|chalu karo)\s+(.+)/)||t.match(/(.+?)\s+(?:kholo|khol do)\b/);
 if(m&&!/\b(avatar|avtar|jarvis|alex|camera)\b/.test(m[1])){const nm=m[1].replace(/\b(app|ko|please)\b/g," ").trim();if(nm&&N.openApp(nm)){say(nm+" khol rahi hoon.".replace("rahi",fem()?"rahi":"raha"));return true}}
 if(/\b(server badlo|change server)\b/.test(t)){N.changeServer();return true}
 return false}
// ---------- router (called from the main hook) ----------
window.ALEXPlus3={
 persona(t0,t){const lead=(t0.match(/^(?:hey |hi |ok )?(alex|jarvis|avatar)\b/)||[])[1];if(!lead)return;
  if(lead!=="alex"){if(!open()&&!/\b(hide|band|chhup\w*|hatao)\b/.test(t))showAvatar()}
  else if(open()&&!/\b(avatar|mode|suit|punch|kick|blast|shield|slash|jump|roar|transform|scan|fly|beam|dodge|slam|flip|salute|victory|charge|combo|uppercut|stance|map|route|danger|khatra|status|show|hide)\b/.test(t))hideAvatar()},
 async handle(t,msg,say){window.__alexSay=say;
  if(EMERG.test(t)||EMERG.test(msg)){if(Date.now()-lastE>12000)await emergency(say);return true}
  if(await phone(t,msg,say))return true;
  if(/\brobot\b/.test(t)){const u=(msg.match(/https?:\/\/\S+/)||[])[0];
   if(u){robot=u;ls.set("alexRobotUrl",u);say("Robot connect kar diya. Ab har action robot ko bhi jayega.");return true}
   if(/\b(off|band|disconnect)\b/.test(t)){robot="";ls.set("alexRobotUrl","");say("Robot disconnect kar diya.");return true}}
  if(/\b(map|maps|naksha|route|raasta|rasta|directions?|navigate|nearby|nearest|near me|meri location|my location|where am i|main kahan|mai kahan|jana hai|jaana hai|kaise jaun)\b/.test(t))return maps(t,say);
  return false}};
})();

/* ===== ALEX PLUS: languages, laptop agent, avatar upgrade ===== */
/* ALEX PLUS 4: every language, JARVIS voice hints, laptop agent, avatar upgrade (captions, task HUD, listening glow, idle life) */
(()=>{
const A=()=>window.ALEXAvatar3D,scr=document.getElementById("avatarScreen"),stage=document.querySelector(".avatar-stage");
const open=()=>!!scr&&scr.classList.contains("visible");
const ls={get:k=>{try{return localStorage.getItem(k)}catch(e){return null}},set:(k,v)=>{try{localStorage.setItem(k,v)}catch(e){}}};
const fem=()=>typeof selectedVoice!=="undefined"&&selectedVoice==="female";
// ---------- voice hints for the server (JARVIS voice, language, emotion) + language hint for the AI ----------
const _f=window.fetch;
window.fetch=function(u,o){try{const url=String(u);
 if(o&&typeof o.body==="string"&&(url.endsWith("/speak")||url.endsWith("/ask"))){const d=JSON.parse(o.body),lg=ls.get("alexLang")||"hi-IN";
  if(url.endsWith("/speak")){d.persona=open()?"avatar":"alex";d.lang=lg.slice(0,2);d.emotion=document.body.dataset.emotion||"neutral"}
  else d.context=("Understand every language. Reply in the language and script the user used in their last message (Hindi/Hinglish stay Hinglish). Voice-input language: "+lg+". "+(d.context||"")).slice(0,3000);
  o={...o,body:JSON.stringify(d)}}}catch(e){}return _f.call(this,u,o)};
// ---------- every language ----------
const LANG={hindi:["hi-IN","ठीक है, अब मैं हिंदी में बात करूँगी।",/hindi|हिंदी|हिन्दी/],english:["en-IN","Okay, I will speak English now.",/english|angrezi|अंग्रेजी|अंग्रेज़ी/],
 gujarati:["gu-IN","હવે હું ગુજરાતીમાં વાત કરીશ.",/gujarati|ગુજરાતી|गुजराती/],tamil:["ta-IN","இனி நான் தமிழில் பேசுவேன்.",/tamil|तमिल/],telugu:["te-IN","ఇకపై నేను తెలుగులో మాట్లాడతాను.",/telugu|तेलुगु/],
 marathi:["mr-IN","आता मी मराठीत बोलेन.",/marathi|मराठी/],bengali:["bn-IN","এখন আমি বাংলায় কথা বলব।",/bengali|bangla|बंगाली/],kannada:["kn-IN","ಈಗ ನಾನು ಕನ್ನಡದಲ್ಲಿ ಮಾತನಾಡುತ್ತೇನೆ.",/kannada|कन्नड/],
 malayalam:["ml-IN","ഇനി ഞാൻ മലയാളത്തിൽ സംസാരിക്കും.",/malayalam|मलयालम/],urdu:["ur-PK","ٹھیک ہے، اب میں اردو میں بات کروں گی۔",/urdu|उर्दू/],nepali:["ne-NP","ठीक छ, अब म नेपालीमा बोल्छु।",/nepali|नेपाली/],
 spanish:["es-ES","De acuerdo, hablaré español.",/spanish|español|स्पेनिश/],french:["fr-FR","D'accord, je parlerai français.",/french|français|फ्रेंच/],german:["de-DE","In Ordnung, ich spreche jetzt Deutsch.",/german|deutsch|जर्मन/],
 portuguese:["pt-BR","Certo, vou falar português.",/portuguese|português/],italian:["it-IT","Va bene, parlerò italiano.",/italian|italiano/],turkish:["tr-TR","Tamam, şimdi Türkçe konuşacağım.",/turkish|türkçe/],
 indonesian:["id-ID","Baik, saya akan berbicara bahasa Indonesia.",/indonesian/],vietnamese:["vi-VN","Được rồi, tôi sẽ nói tiếng Việt.",/vietnamese/],
 japanese:["ja-JP","了解しました。日本語で話します。",/japanese|जापानी/],korean:["ko-KR","알겠습니다. 한국어로 말할게요.",/korean|कोरियन/],chinese:["zh-CN","好的，我现在说中文。",/chinese|mandarin|चीनी/],
 arabic:["ar-SA","حسنًا، سأتحدث العربية الآن.",/arabic|अरबी/],russian:["ru-RU","Хорошо, теперь я буду говорить по-русски.",/russian|रूसी/],thai:["th-TH","ได้เลย ฉันจะพูดภาษาไทยตอนนี้",/thai|थाई/]};
function setLang(code){ls.set("alexLang",code);try{if(typeof recognition!=="undefined"&&recognition){recognition.lang=code;try{recognition.stop()}catch(e){}}}catch(e){}}
const lgt=setInterval(()=>{const c=ls.get("alexLang");if(c&&typeof recognition!=="undefined"&&recognition){recognition.lang=c;clearInterval(lgt)}},1000);setTimeout(()=>clearInterval(lgt),60000);
function language(t,msg,say){const s=(t+" "+msg).toLowerCase();
 if(/\b(song|gaana|gana|movie|film|news|khabar|video|dictionary|translate)\b/.test(s))return false;
 if(!(/\b(mein|me|mai)\s+(baat|bolo|bol|speak|talk|samjho|suno)\b|\b(speak|talk)\b|\blanguage\b|\bbhasha\b|\bmode\b|भाषा|में\s*(बात|बोलो|बोल)/.test(s)))return false;
 for(const k in LANG)if(LANG[k][2].test(s)){setLang(LANG[k][0]);say(LANG[k][1]);return true}
 return false}
// ---------- laptop agent: any task ----------
const TASKV=/\b(open|kholo|khol|chalao|chala|bajao|baja|play|search|dhundo|dhoondo|google|youtube|chrome|notepad|calculator|word|excel|vscode|folder|file|type|likho|likh|write|close|band karo|volume|mute|screenshot|tab|download|scroll|click|minimize|maximize|copy|paste|save|lock|laptop|computer|pc|desktop|window|spotify|gmail|jao|bhejo|bana|create|new|install)\b/;
const NOTTASK=/\b(kaise|kyun|why|how|explain|samjha\w*|what is|kya hai|kaun|meaning|matlab)\b/;
let pendA=null;
async function run(task,confirm,say){showTask(task);
 try{const r=await apiRequest("/plus/agent",{method:"POST",body:JSON.stringify({task,confirm})});
  if(!r.handled)return false;
  if(r.needs_confirm){pendA={task,t:Date.now()};say((r.say||"Ye kaam sensitive hai.")+" Haan bolein to kar dungi.".replace("dungi",fem()?"dungi":"dunga"));return true}
  if(open())A()?.gesture("nod");
  const lines=(r.results||[]).map(x=>(x.ok?"OK   ":"FAIL ")+x.step+": "+x.msg).join("\n");
  if(lines)addMessage("assistant","TASK RESULT\n"+lines);
  say((r.say||"Ho gaya.")+(r.hint?" "+r.hint:""));return true
 }catch(e){return false}}
async function agent(t,msg,say){
 if(pendA&&Date.now()-pendA.t<30000){
  if(/^(haan|han|yes|kar do|kardo|ok|chalao)$/.test(t)){const p=pendA;pendA=null;return run(p.task,true,say)}
  if(/^(nahi|no|cancel|mat)$/.test(t)){pendA=null;say("Theek hai, cancel kar diya.");return true}}
 if(!TASKV.test(t)||NOTTASK.test(t)||t.split(" ").length<2)return false;
 return run(msg,false,say)}
// ---------- avatar upgrade: live captions, task HUD, listening glow, idle life ----------
let capEl=null,taskEl=null,capT=0,taskT=0;
if(stage){const st=document.createElement("style");
 st.textContent=".av-cap{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:3;width:min(720px,86%);text-align:center;pointer-events:none;font:15px/1.45 system-ui,sans-serif;color:#dff;text-shadow:0 0 10px #00eaff88}.av-cap small{display:block;opacity:.55;font-size:12px;margin-bottom:3px}.jv-task{position:absolute;top:150px;left:16px;z-index:3;pointer-events:none;font:11px monospace;letter-spacing:1px;color:#ffd84a;text-shadow:0 0 8px currentColor;max-width:260px}.avatar-stage.av-listen::after{content:'';position:absolute;inset:0;box-shadow:inset 0 0 70px rgba(0,234,255,.28);pointer-events:none;z-index:1}";
 document.head.appendChild(st);
 capEl=document.createElement("div");capEl.className="av-cap";stage.appendChild(capEl);
 taskEl=document.createElement("div");taskEl.className="jv-task";stage.appendChild(taskEl)}
function showTask(t){if(!taskEl)return;taskEl.textContent="TASK: "+String(t).slice(0,60);clearTimeout(taskT);taskT=setTimeout(()=>taskEl.textContent="",9000)}
function cap(kind,text){if(!capEl||!open())return;capEl.textContent="";const s=document.createElement("small");s.textContent=kind==="user"?"YOU":"AVATAR";capEl.append(s,document.createTextNode(String(text).slice(0,170)));clearTimeout(capT);capT=setTimeout(()=>capEl.textContent="",9000)}
const chat=document.getElementById("chatMessages");
if(chat)new MutationObserver(m=>m.forEach(r=>r.addedNodes.forEach(n=>{if(n.nodeType!==1||n.querySelector("a"))return;const tx=(n.textContent||"").trim();if(!tx)return;
 cap(/assistant|alex/i.test(n.className+(n.dataset?.role||""))?"ai":"user",tx)}))).observe(chat,{childList:true});
setInterval(()=>{if(!stage)return;const s=document.getElementById("listenStatus")?.textContent||"";stage.classList.toggle("av-listen",open()&&/SUN|LISTEN/i.test(s)&&!(typeof isSpeaking!=="undefined"&&isSpeaking))},500);
setInterval(()=>{if(open()&&!(typeof isSpeaking!=="undefined"&&isSpeaking)){Math.random()<.5?A()?.gesture("nod"):A()?.setEmotion("thinking",1600)}},22000);
window.ALEXPlus4={handle:async(t,msg,say)=>{
 if(/\b(mujhe|muje|mereko)\s+call\s+(karo|kar do|lagao)\b|\bcall me\b/.test(t)){
  try{const r=await apiRequest("/phone/callme",{method:"POST",body:"{}"});say(r.success?("Theek hai, abhi aapko call laga "+(fem()?"rahi":"raha")+" hoon."):"Call nahi lag paaya: "+(r.error||""))}
  catch(e){say("Phone calling set nahi hai. PHONE_CALL_SETUP.txt dekhein.")}return true}
 return language(t,msg,say)},agent};
})();

/* ===== ALEX PLUS: emotions, news, skills, modes, voice, barge-in ===== */
/* ALEX PLUS (front-end): emotions, India news, device skills. Hologram untouched. */
(()=>{
const A=()=>window.ALEXAvatar3D,say=t=>{try{addMessage("assistant",t)}catch(e){}try{speakText(t)}catch(e){}};
const norm=s=>String(s||"").toLowerCase().replace(/[^\p{L}\p{M}\p{N}\s+]/gu," ").replace(/\s+/g," ").trim();
const phone=/Android|iPhone|iPad/i.test(navigator.userAgent);
// ---------- Hindi script -> roman (so voice in Hindi is understood) ----------
const DEV={"एलेक्स":"alex","अवतार":"avatar","अवतर":"avatar","दिखाओ":"dikhao","दिखा":"dikha","दिखाइए":"dikhao","खोलो":"kholo","छुपाओ":"chhupao","बंद":"band","फाइटिंग":"fighting","फाइट":"fight","डेंजर":"danger","खतरा":"khatra","वायरस":"virus","स्कैनिंग":"scanning","स्कैन":"scan","पावर":"power","नॉर्मल":"normal","मोड":"mode","मुक्का":"mukka","लात":"laat","तलवार":"talwar","ढाल":"dhal","कूदो":"kudo","दहाड़":"dahad","दहाड":"dahad","ट्रांसफॉर्म":"transform","करो":"karo","अपना":"apna","शो":"show","योर":"your","जार्विस":"jarvis","जारविस":"jarvis","बात":"baat","रुको":"ruko","चुप":"chup","बस":"bas","करनी":"karni","दूसरा":"dusra","रूप":"roop","वापस":"wapas","ब्लास्ट":"blast","पंच":"punch","किक":"kick","जंप":"jump","शील्ड":"shield","खबर":"khabar","न्यूज़":"news","न्यूज":"news"};
const rom=s=>{let r=String(s||"");for(const k in DEV)r=r.split(k).join(" "+DEV[k]+" ");return r};
// ---------- DEMON VOICE: avatar speaks deep and layered while the avatar screen is open ----------
let vmode="jarvis";const avOpen=()=>document.getElementById("avatarScreen")?.classList.contains("visible");
const NA=window.Audio;
window.Audio=function(src){const a=new NA(src);if(vmode!=="normal"&&avOpen()){a.preservesPitch=a.mozPreservesPitch=a.webkitPreservesPitch=false;a.playbackRate=vmode==="demon"?.78:1}return a};
window.Audio.prototype=NA.prototype;
// ---------- emotions ----------
const EMO={sad:/\b(sad|udaas|dukhi|dukh|ro raha|ro rahi|cry|depress\w*|akela|akeli|lonely|dil toot\w*|bura lag\w*)\b/,
 stress:/\b(stress\w*|tension|pareshan\w*|worried|chinta|anxious|ghabra\w*|thak\w*|tired|dar lag\w*)\b/,
 angry:/\b(gussa|angry|irritat\w*|hate|nafrat|bakwas|frustrat\w*)\b/,
 excited:/\b(excited|wow|amazing|congrat\w*|jeet\w*|won|selected|pass ho\w*|party)\b/,
 happy:/\b(happy|khush|mast|awesome|great|badhiya|zabardast|maza|thanks|thank you|shukriya|dhanyavad|love)\b/,
 surprised:/\b(really|sach mein|seriously|kya baat|omg|shocked)\b/,
 thinking:/\b(soch|think|confused|samajh nahi|kaise|why|kyun|how)\b/};
const detect=t=>{const s=norm(t);for(const k in EMO)if(EMO[k].test(s))return k;return"neutral"};
const setEmo=e=>{A()?.setEmotion(e);document.body.dataset.emotion=e};
const chat=document.getElementById("chatMessages");
if(chat)new MutationObserver(m=>m.forEach(r=>r.addedNodes.forEach(n=>{if(n.nodeType!==1)return;const t=n.textContent||"";
 if(/assistant|alex/i.test(n.className+n.dataset?.role)){if(/\b(hello|hi|namaste|welcome|hey)\b/i.test(t.slice(0,40)))A()?.gesture("wave");else setEmo(detect(t))}}))).observe(chat,{childList:true});
// ---------- news ----------
const PLACES="ahmedabad|gujarat|surat|rajkot|vadodara|mumbai|delhi|kolkata|chennai|bengaluru|bangalore|hyderabad|pune|jaipur|lucknow|patna|bhopal|punjab|kerala|bihar|maharashtra|rajasthan|kashmir|goa|assam|odisha|uttar pradesh|madhya pradesh".split("|");
const TOP={world:/world|duniya|international|videsh/,sports:/sport|cricket|khel|ipl|football/,business:/business|market|share|economy|sensex|nifty/,technology:/tech|ai\b/,entertainment:/bollywood|entertainment|movie|film/,science:/science|isro|space/,health:/health|sehat/};
async function news(msg,t){
 let topic="india",q="";for(const k in TOP)if(TOP[k].test(t)){topic=k;break}
 for(const p of PLACES)if(t.includes(p)){q=p;break}
 const dev=/[\u0900-\u097F]/.test(msg),hin=dev||/\b(batao|bata|aaj|khabar\w*|samachar|sunao|kya)\b/.test(t);
 say(hin?"Ek second, taaza khabrein la raha hoon...":"One moment, fetching the latest news...");
 try{const r=await apiRequest(`/plus/news?topic=${topic}&q=${encodeURIComponent(q)}&lang=${dev?"hi":"en"}&limit=6&summarize=1&style=${hin?"hinglish":"en"}`);
  const list=r.items.map((x,i)=>`${i+1}. ${x.title} (${x.source})`).join("\n");
  addMessage("assistant","LIVE NEWS - "+(q||topic).toUpperCase()+"\n"+list);
  speakText(r.summary||r.items.slice(0,3).map(x=>x.title).join(". "));
 }catch(e){say(hin?"Abhi news nahi la paaya. Internet check karo.":"I could not fetch the news. Please check your internet.")}}
// ---------- device skills ----------
let torchStream=null,wake=null;
async function torch(on){try{if(!on){torchStream?.getTracks().forEach(t=>t.stop());torchStream=null;return"Torch off kar di."}
 torchStream=await navigator.mediaDevices.getUserMedia({video:{facingMode:"environment"}});const tr=torchStream.getVideoTracks()[0];
 await tr.applyConstraints({advanced:[{torch:true}]});return"Torch on hai."}catch(e){return"Is device par torch browser se control nahi ho paayi."}}
function beep(){try{const c=new AudioContext(),o=c.createOscillator();o.connect(c.destination);o.frequency.value=880;o.start();setTimeout(()=>{o.stop();c.close()},700)}catch(e){}}
const APPS={whatsapp:"https://wa.me/",instagram:"https://www.instagram.com",facebook:"https://www.facebook.com",gmail:"https://mail.google.com",telegram:"https://t.me",spotify:"https://open.spotify.com",youtube:"https://www.youtube.com",twitter:"https://x.com",linkedin:"https://www.linkedin.com"};
const MODES={fighting:/\b(fight\w*|fiting|faiting|ladai|combat|yudh)\b/,danger:/\b(danger\w*|dangar|khatra|khatarnak|alert)\b/,virus:/\b(virus|malware|hack\w*)\b/,scanning:/\b(scan\w*|jaanch)\b/,power:/\b(power|shakti|taakat|ultra)\b/,normal:/\b(normal|shant|calm)\b/};
const ACT={punch:/\b(punch|mukka|ghoosa)\b/,kick:/\b(kick|laat)\b/,slash:/\b(slash|sword|talwar|blade|vaar)\b/,blast:/\b(blast|shoot|goli|fire kar\w*|dhamaka)\b/,shield:/\b(shield|dhal|defend|bachao|block)\b/,jump:/\b(jump|kudo|koodo|uchhal\w*)\b/,roar:/\b(roar|dahad\w*|garjo|chillao)\b/,uppercut:/\b(uppercut)\b/,roundhouse:/\b(roundhouse|spin kick)\b/,dodge:/\b(dodge|bacho|side hato|hat jao)\b/,flip:/\b(flip|backflip|palti)\b/,slam:/\b(slam|ground slam)\b/,fly:/\b(fly|udo|ud jao|flight|hover)\b/,beam:/\b(beam|laser)\b/,combo:/\b(combo)\b/,salute:/\b(salute|salaam|salam)\b/,victory:/\b(victory|jeet gaye)\b/,charge:/\b(power up|charge up|energy charge)\b/,stance:/\b(stance|ready position|guard)\b/};
const LINES={punch:"Punch deploy, Sir.",kick:"Kick ready, Sir.",slash:"Blade active, Sir.",blast:"Repulsor blast, Sir. Fire!",shield:"Shield up, Sir.",jump:"Thrusters engaged, Sir.",roar:"Sir, power level maximum!",uppercut:"Uppercut, Sir.",roundhouse:"Spin kick, Sir.",dodge:"Evasive manoeuvre, Sir.",flip:"Backflip, Sir.",slam:"Ground slam, Sir. Impact!",fly:"Flight mode, Sir. Thrusters at full.",beam:"Laser beam charged, Sir. Fire!",combo:"Combo attack, Sir.",salute:"Salute, Sir.",victory:"Mission accomplished, Sir.",charge:"Charging power core, Sir.",stance:"Combat stance, Sir."};
const MODELINE={fighting:"Combat mode active, Sir.",danger:"Threat protocol on, Sir. Sab alert hai.",virus:"Virus analysis mode, Sir.",scanning:"Scan shuru, Sir.",power:"Full power, Sir.",normal:"Standby mode, Sir."};
const SKILLS="Main ye kar sakta hoon:\n- Avatar: \"show avatar\" / \"avatar dikhao\", \"hide avatar\", transform\n- Modes: normal, danger, fighting, virus, scanning, power (jaise \"fighting mode on\")\n- Fighting skills: punch, kick, uppercut, roundhouse, slash, blast, laser beam, shield, dodge, jump, backflip, ground slam, fly, combo, stance, charge, salute, victory, roar\n- Demon awaaz: avatar khulne par meri awaaz bhaari ho jaati hai (\"demon voice off\" se band)\n- Aur bhi:\n- Live India news (\"aaj ki khabrein\", \"cricket news\", \"Gujarat news\")\n- Dost ki tarah baat aur aapka mood samajhna\n- Avatar: show avatar, wave, nod, dance, 360, modes\n- Battery, torch, vibrate, fullscreen, screen awake, timer\n- Phone par apps kholna, Maps aur calling\n- Memory, tasks, files aur computer control (PC par)\nNote: browser se SMS, contacts ya silent calls possible nahi. Uske liye Android app chahiye.";
async function skill(msg,t){
  let m;
 if(/\b(demon voice|jarvis voice|normal voice)\b/.test(t)){vmode=/normal voice/.test(t)||/\b(off|band)\b/.test(t)?(/jarvis/.test(t)?"jarvis":"normal"):(/demon/.test(t)?"demon":"jarvis");say(vmode==="demon"?"Demon voice on, Sir.":vmode==="jarvis"?"Jarvis voice active, Sir.":"Normal voice, Sir.");return true}
  if(/\b(interrupt|barge)\b/.test(t)){bargeOn=!/\b(off|band)\b/.test(t);say(bargeOn?"Ab aap bolenge to main ruk jaaunga.":"Interrupt band kar diya.");return true}
  const w=t.split(" ");
 if(w.length<=2&&/^(stop|ruko|ruk jao|chup|bas|shant|chup ho jao)$/.test(t)){stopSpeech();return true}
  const full=norm(rom(msg)).replace(/\b(avtar|avtaar|awatar|avtara)\b/g,"avatar");
 if(window.ALEXPlus3&&await window.ALEXPlus3.handle(t,msg,say))return true;
 if(window.ALEXPlus4&&await window.ALEXPlus4.handle(t,msg,say))return true;
 if(window.ALEXJarvis&&await window.ALEXJarvis.handle(t,full,say))return true;
 if(window.ALEXPlus2&&await window.ALEXPlus2.handle(t,msg,say))return true;
 if(/\bavatar\b.*\b(baat|bat|talk)\b|\b(dusra|doosra|second)\s+(roop|rup|form)\b|\bavatar (form|ban jao)\b/.test(full)){if(!avOpen())showAvatar();setTimeout(()=>say("Sir, avatar online. Saare systems ready. Hukum dijiye."),avOpen()?0:900);return true}
 if(/\balex\b.*\bse\b.*\b(baat|bat|talk)\b|\b(normal|asli|pehle wale)\s+alex\b|\balex (wapas|back)\b|\bavatar (wapas|hatao)\b/.test(full)){if(avOpen())hideAvatar();say("Haan, main ALEX hoon. Bolo, kya karna hai?");return true}
 const avWord=/\b(avatar|avtar|avtaar|awatar|avtara)\b/.test(t);
 if(avWord&&/\b(hide|band|chhup\w*|close|hatao|exit)\b/.test(t)){hideAvatar();say("Avatar chhupa diya.");return true}
 if(avWord&&/\b(show|dikha\w*|open|khol\w*|display|dekh\w*|aao|samne|kaha|where)\b/.test(t)){showAvatar();setTimeout(()=>say("At your service, Sir. Hukum dijiye."),700);return true}
 const wantModeWord=/\b(mode|avatar|avtar|activate|chalu|lagao|switch|change|ho jao|ban jao|on karo|on)\b/.test(t)||(avOpen()&&t.split(" ").length<=3);
 if(wantModeWord)for(const k in MODES)if(MODES[k].test(t)){if(!avOpen())showAvatar();setAvatarMode(k);if(k==="fighting")setTimeout(()=>A()?.gesture("roar"),500);setTimeout(()=>say(MODELINE[k]),500);return true}
 const doIt=avOpen()||/\b(karo|kar do|dikhao|chalao|maro|laga\w*|do)\b/.test(t);
 if(doIt)for(const k in ACT)if(ACT[k].test(t)){if(!avOpen())showAvatar();setTimeout(()=>{A()?.gesture(k);say(LINES[k])},avOpen()?0:800);return true}
 if(/\b(fighting skills|skills dikhao|fight skills)\b/.test(t)){if(!avOpen())showAvatar();say("Mere fighting skills: punch, kick, uppercut, roundhouse, slash, blast, beam, shield, dodge, jump, flip, slam, fly, combo, stance, charge, salute, victory aur roar. Bolo kya dikhaoon?");return true}
 if(/\b(news|khabar\w*|samachar|headlines)\b/.test(t)){await news(msg,t);return true}
 if(/\b(what can you do|skills|tum kya kar|kya kar sakte|help me with)\b/.test(t)){say(SKILLS);return true}
 if(/\b(transform|rup badlo)\b/.test(t)){const sc=document.getElementById("avatarScreen");if(!sc?.classList.contains("visible"))showAvatar();else A()?.transform();say("Transforming!");return true}
 if(/\b(wave|hi karo|haath hila\w*)\b/.test(t)){A()?.gesture("wave");say("Hello! Main yahin hoon.");return true}
 if(/\b(dance|nacho|naach)\b/.test(t)){A()?.gesture("dance");A()?.setEmotion("excited",4000);say("Ye dekho mere moves!");return true}
 if(/\b(nod|sir hila\w*)\b/.test(t)){A()?.gesture("nod");say("Ji haan.");return true}
 if(/\bbattery\b/.test(t)){if(!navigator.getBattery){say("Is browser mein battery info nahi milti.");return true}
  const b=await navigator.getBattery();say(`Battery ${Math.round(b.level*100)} percent hai${b.charging?", aur charging chal rahi hai.":"."}`);return true}
 if(/\b(vibrate|vibration)\b/.test(t)){say(navigator.vibrate?(navigator.vibrate([200,100,200]),"Vibrate kar diya."):"Ye device vibration support nahi karta.");return true}
 if(/\b(torch|flashlight|flash light)\b/.test(t)){say(await torch(!/\b(off|band|bujha\w*)\b/.test(t)));return true}
 if(/\bfull ?screen\b/.test(t)){if(/\b(off|exit|band)\b/.test(t))document.exitFullscreen?.();else document.documentElement.requestFullscreen?.();say("Theek hai.");return true}
 if(/\b(keep|screen).*(awake|on)\b|\bawake mode\b/.test(t)){try{wake=await navigator.wakeLock.request("screen");say("Screen ab band nahi hogi.")}catch(e){say("Ye device screen awake support nahi karta.")}return true}
 if((m=t.match(/(\d+)\s*(second|sec|minute|min|hour|ghanta|ghante)\w*/))&&/\b(timer|alarm|remind\w*|yaad)\b/.test(t)){
  const n=+m[1],u=/^(h|g)/.test(m[2])?3600:/^m/.test(m[2])?60:1;
  setTimeout(()=>{beep();navigator.vibrate?.([300,150,300]);say("Timer khatam! Aapka time ho gaya.");try{new Notification("ALEX",{body:"Timer complete"})}catch(e){}},n*u*1000);
  try{Notification.requestPermission()}catch(e){}say(`${n} ${m[2]} ka timer laga diya.`);return true}
 if(phone&&(m=t.match(/\b(?:open|kholo|khol do|chalu karo)\s+(\w+)|\b(\w+)\s+(?:kholo|khol do|open karo)\b/))){
  const app=m[1]||m[2];if(APPS[app]){window.open(APPS[app],"_blank");say(app+" khol raha hoon.");return true}}
 if(window.ALEXPlus4&&await window.ALEXPlus4.agent(t,msg,say))return true;
 return false}
// ---------- barge-in: when you speak over ALEX, it stops and listens ----------
let bargeOn=true,vad=null,hot=0,ema=0;
async function initVAD(){if(vad)return;try{const st=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true}});
 const c=new(window.AudioContext||window.webkitAudioContext)();c.resume?.();const an=c.createAnalyser();an.fftSize=1024;c.createMediaStreamSource(st).connect(an);
 const buf=new Float32Array(an.fftSize);vad=true;
 setInterval(()=>{const playing=typeof alexAudio!=="undefined"&&alexAudio&&!alexAudio.paused&&alexAudio.currentTime>.7;
  if(!bargeOn||!playing){hot=0;ema=0;return}
  an.getFloatTimeDomainData(buf);let q=0;for(const v of buf)q+=v*v;const rms=Math.sqrt(q/buf.length);
  ema=ema?ema*.92+rms*.08:rms;
  if(rms>.05&&rms>ema*1.8)hot++;else hot=Math.max(0,hot-1);
  if(hot>=2){hot=0;stopSpeech();try{scheduleRecognitionRestart(80)}catch(e){}}},60)
 }catch(e){console.warn("ALEX barge-in off:",e)}}
["pointerdown","keydown"].forEach(ev=>addEventListener(ev,initVAD,{once:true}));
// ---------- hook (no edit to script.js) ----------
// tell the AI which form is speaking (only while the avatar is open)
const _f=window.fetch;window.fetch=function(u,o){try{if(String(u).endsWith("/ask")&&o&&typeof o.body==="string"){const h=[];
 if(typeof selectedVoice!=="undefined"&&selectedVoice==="female")h.push("You speak with a lovely, warm female Indian voice: use feminine Hindi forms (karti hoon, rahi hoon, gayi) and sound natural and human.");
 if(avOpen())h.push("AVATAR FORM ACTIVE: you are the AVATAR of ALEX, in the style of Tony Stark's J.A.R.V.I.S. - calm, refined, quietly witty, extremely capable and proactive. Address the user as 'Sir'. Keep replies short and sharp, in the user's language (Hinglish is fine). Confirm commands briefly ('Right away, Sir.'). Warn about risks and suggest next steps. Call yourself 'Avatar', never say 'I am ALEX', never claim abilities the app lacks, never invent status data.");
 if(window.__alexOwnerHint){h.push("The user's voice was just recognised as your owner. Greet them warmly in one short line first, as if you are genuinely happy to hear them.");window.__alexOwnerHint=false}
 if(h.length){const d=JSON.parse(o.body);d.context=(h.join(" ")+" "+(d.context||"")).slice(0,3000);o={...o,body:JSON.stringify(d)}}}}catch(e){}return _f.call(this,u,o)};
const orig=window.processUserMessage;
if(typeof orig==="function")window.processUserMessage=async function(raw,source="text"){
 const msg=String(raw||"").trim();if(!msg)return orig.apply(this,arguments);
 if(window.__alexMute)return;
 if(source!=="text"){const vc=window.ALEXPlus2?.voiceCheck();if(vc&&vc.owner&&Date.now()-(window.__lastOwner||0)>600000){window.__lastOwner=Date.now();window.__alexOwnerHint=true;setEmo("happy");if(avOpen())A()?.gesture("wave")}}
 const t=norm(rom(msg).replace(/^\s*(hey |hi |ok )?(alex|jarvis)[, ]*/i,"")),jv=/^\s*(hey |hi |ok )?jarvis\b/i.test(rom(msg));window.ALEXPlus3?.persona(norm(rom(msg)),t);setEmo(detect(t));
 try{if(await skill(msg,t)){if(source==="text")try{addMessage("user",msg)}catch(e){}return}}catch(e){console.warn("ALEX Plus skill error",e)}
 return orig.call(this,jv?(rom(msg).replace(/^\s*(hey |hi |ok )?jarvis[, ]*/i,"").trim()||msg):msg,source)};
console.log("ALEX Plus loaded");
})();
