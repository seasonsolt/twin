import{b1 as Ct,bz as jr,aD as Pt,S as ea,C as et,am as ta,aK as Je,aB as We,aO as _t,dG as si,f as $t,aH as _r,aQ as li,dJ as Mt,a7 as nt,m as Kt,aC as Dt,x as Lt,ac as St,a8 as sn,g as Ne,dN as na,cf as ci,bO as ia,bP as ra,br as tn,bQ as aa,bR as oa,bS as sa,bT as la,bU as ca,bV as fa,bW as da,bX as ua,bY as pa,bZ as ha,b_ as ma,b$ as _a,c0 as ga,c1 as va,bs as Sa,r as Ea,s as Vn,R as xa,n as Cn,p as vt,N as un,o as Ma,q as Vt,bB as Ta,bC as Aa,bD as qn,bE as Ra,bF as Zn,bG as ba,bH as Ca,bI as Pa,dO as La,dP as Ua,af as It,V as gt,B as xn,k as Wn,E as Nt,aE as mn,aF as wa,c6 as wt,aP as an,bc as Qt,bn as Sn,b6 as Bt,ba as Jt,dx as Da,b5 as Wt,d5 as fi,dQ as Ia,Y as gr,bx as $e,bl as Na,W as _n,bo as ya,bt as Pn,aN as Ut,bb as qt,bi as ln,d0 as Fa,cU as Oa,aJ as Ba,bK as Yt,ai as Fe,at as Ga,cj as vr,bd as Sr,b9 as Er,b3 as En,bg as xr,bh as Mr,cb as Ha,cc as Va,cd as Wa,ce as ka,cg as za,ch as Xa,ci as Ya,c2 as Ka,c3 as di,c4 as qa,ca as gn,bq as Za,c7 as ui,c8 as pi,c9 as hi,ah as $a,bw as Mn,ag as mi,dF as Qa,du as $n,dR as kn,bp as Tr,dS as Ar,d1 as Rr,dv as Ja,dT as br,bj as ja,bk as eo,b0 as to,b2 as no,b4 as Cr,b7 as io,be as ro,b8 as ao,ck as Ln,cl as Un,cm as wn,cn as Dn,co as _i,cp as gi,cq as vi,cr as Si,cs as Ei,ct as xi,cu as Mi,cv as Ti,cw as Ai,cx as zn,cy as Ri,cz as bi,cA as Ci,cB as Pi,cC as Li,cD as Ui,cE as wi,cF as Di,cG as Ii,cH as Ni,cI as yi,cJ as Fi,cK as Oi,cL as Bi,cM as Gi,cN as Hi,cO as Vi,cP as Wi,cQ as ki,cR as zi,cS as Xn,cT as Xi,ds as Pr,bL as Yi,bJ as Lr,dU as Ki,dV as mt,dW as oo,dX as Ur,a$ as wr,a_ as Dr,aZ as Ir,aY as Nr,aX as yr,aW as Fr,bu as In,bv as Nn,d3 as so,d4 as lo,d as Or,dB as cn,dC as jt,y as co,dY as fo,dp as uo,dq as po,dr as ho,dZ as mo,a3 as _o,dm as go,bN as vo,bM as So}from"./three.core-DsCCCDJ3.js";function Br(){let e=null,n=!1,t=null,i=null;function l(o,d){i=e.requestAnimationFrame(l),t(o,d)}return{start:function(){n!==!0&&t!==null&&e!==null&&(i=e.requestAnimationFrame(l),n=!0)},stop:function(){e!==null&&e.cancelAnimationFrame(i),n=!1},setAnimationLoop:function(o){t=o},setContext:function(o){e=o}}}function Eo(e){const n=new WeakMap;function t(g,R){const T=g.array,H=g.usage,I=T.byteLength,p=e.createBuffer();e.bindBuffer(R,p),e.bufferData(R,T,H),g.onUploadCallback();let M;if(T instanceof Float32Array)M=e.FLOAT;else if(typeof Float16Array<"u"&&T instanceof Float16Array)M=e.HALF_FLOAT;else if(T instanceof Uint16Array)g.isFloat16BufferAttribute?M=e.HALF_FLOAT:M=e.UNSIGNED_SHORT;else if(T instanceof Int16Array)M=e.SHORT;else if(T instanceof Uint32Array)M=e.UNSIGNED_INT;else if(T instanceof Int32Array)M=e.INT;else if(T instanceof Int8Array)M=e.BYTE;else if(T instanceof Uint8Array)M=e.UNSIGNED_BYTE;else if(T instanceof Uint8ClampedArray)M=e.UNSIGNED_BYTE;else throw new Error("THREE.WebGLAttributes: Unsupported buffer data format: "+T);return{buffer:p,type:M,bytesPerElement:T.BYTES_PER_ELEMENT,version:g.version,size:I}}function i(g,R,T){const H=R.array,I=R.updateRanges;if(e.bindBuffer(T,g),I.length===0)e.bufferSubData(T,0,H);else{I.sort((M,N)=>M.start-N.start);let p=0;for(let M=1;M<I.length;M++){const N=I[p],W=I[M];W.start<=N.start+N.count+1?N.count=Math.max(N.count,W.start+W.count-N.start):(++p,I[p]=W)}I.length=p+1;for(let M=0,N=I.length;M<N;M++){const W=I[M];e.bufferSubData(T,W.start*H.BYTES_PER_ELEMENT,H,W.start,W.count)}R.clearUpdateRanges()}R.onUploadCallback()}function l(g){return g.isInterleavedBufferAttribute&&(g=g.data),n.get(g)}function o(g){g.isInterleavedBufferAttribute&&(g=g.data);const R=n.get(g);R&&(e.deleteBuffer(R.buffer),n.delete(g))}function d(g,R){if(g.isInterleavedBufferAttribute&&(g=g.data),g.isGLBufferAttribute){const H=n.get(g);(!H||H.version<g.version)&&n.set(g,{buffer:g.buffer,type:g.type,bytesPerElement:g.elementSize,version:g.version});return}const T=n.get(g);if(T===void 0)n.set(g,t(g,R));else if(T.version<g.version){if(T.size!==g.array.byteLength)throw new Error("THREE.WebGLAttributes: The size of the buffer attribute's array buffer does not match the original size. Resizing buffer attributes is not supported.");i(T.buffer,g,R),T.version=g.version}}return{get:l,remove:o,update:d}}var xo=`#ifdef USE_ALPHAHASH
	if ( diffuseColor.a < getAlphaHashThreshold( vPosition ) ) discard;
#endif`,Mo=`#ifdef USE_ALPHAHASH
	const float ALPHA_HASH_SCALE = 0.05;
	float hash2D( vec2 value ) {
		return fract( 1.0e4 * sin( 17.0 * value.x + 0.1 * value.y ) * ( 0.1 + abs( sin( 13.0 * value.y + value.x ) ) ) );
	}
	float hash3D( vec3 value ) {
		return hash2D( vec2( hash2D( value.xy ), value.z ) );
	}
	float getAlphaHashThreshold( vec3 position ) {
		float maxDeriv = max(
			length( dFdx( position.xyz ) ),
			length( dFdy( position.xyz ) )
		);
		float pixScale = 1.0 / ( ALPHA_HASH_SCALE * maxDeriv );
		vec2 pixScales = vec2(
			exp2( floor( log2( pixScale ) ) ),
			exp2( ceil( log2( pixScale ) ) )
		);
		vec2 alpha = vec2(
			hash3D( floor( pixScales.x * position.xyz ) ),
			hash3D( floor( pixScales.y * position.xyz ) )
		);
		float lerpFactor = fract( log2( pixScale ) );
		float x = ( 1.0 - lerpFactor ) * alpha.x + lerpFactor * alpha.y;
		float a = min( lerpFactor, 1.0 - lerpFactor );
		vec3 cases = vec3(
			x * x / ( 2.0 * a * ( 1.0 - a ) ),
			( x - 0.5 * a ) / ( 1.0 - a ),
			1.0 - ( ( 1.0 - x ) * ( 1.0 - x ) / ( 2.0 * a * ( 1.0 - a ) ) )
		);
		float threshold = ( x < ( 1.0 - a ) )
			? ( ( x < a ) ? cases.x : cases.y )
			: cases.z;
		return clamp( threshold , 1.0e-6, 1.0 );
	}
#endif`,To=`#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, vAlphaMapUv ).g;
#endif`,Ao=`#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,Ro=`#ifdef USE_ALPHATEST
	#ifdef ALPHA_TO_COVERAGE
	diffuseColor.a = smoothstep( alphaTest, alphaTest + fwidth( diffuseColor.a ), diffuseColor.a );
	if ( diffuseColor.a == 0.0 ) discard;
	#else
	if ( diffuseColor.a < alphaTest ) discard;
	#endif
#endif`,bo=`#ifdef USE_ALPHATEST
	uniform float alphaTest;
#endif`,Co=`#ifdef USE_AOMAP
	float ambientOcclusion = ( texture2D( aoMap, vAoMapUv ).r - 1.0 ) * aoMapIntensity + 1.0;
	reflectedLight.indirectDiffuse *= ambientOcclusion;
	#if defined( USE_CLEARCOAT ) 
		clearcoatSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_SHEEN ) 
		sheenSpecularIndirect *= ambientOcclusion;
	#endif
	#if defined( USE_ENVMAP ) && defined( STANDARD )
		float dotNV = saturate( dot( geometryNormal, geometryViewDir ) );
		reflectedLight.indirectSpecular *= computeSpecularOcclusion( dotNV, ambientOcclusion, material.roughness );
	#endif
#endif`,Po=`#ifdef USE_AOMAP
	uniform sampler2D aoMap;
	uniform float aoMapIntensity;
#endif`,Lo=`#ifdef USE_BATCHING
	#if ! defined( GL_ANGLE_multi_draw )
	#define gl_DrawID _gl_DrawID
	uniform int _gl_DrawID;
	#endif
	uniform highp sampler2D batchingTexture;
	uniform highp usampler2D batchingIdTexture;
	mat4 getBatchingMatrix( const in float i ) {
		int size = textureSize( batchingTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( batchingTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( batchingTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( batchingTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( batchingTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
	float getIndirectIndex( const in int i ) {
		int size = textureSize( batchingIdTexture, 0 ).x;
		int x = i % size;
		int y = i / size;
		return float( texelFetch( batchingIdTexture, ivec2( x, y ), 0 ).r );
	}
#endif
#ifdef USE_BATCHING_COLOR
	uniform sampler2D batchingColorTexture;
	vec4 getBatchingColor( const in float i ) {
		int size = textureSize( batchingColorTexture, 0 ).x;
		int j = int( i );
		int x = j % size;
		int y = j / size;
		return texelFetch( batchingColorTexture, ivec2( x, y ), 0 );
	}
#endif`,Uo=`#ifdef USE_BATCHING
	mat4 batchingMatrix = getBatchingMatrix( getIndirectIndex( gl_DrawID ) );
#endif`,wo=`vec3 transformed = vec3( position );
#ifdef USE_ALPHAHASH
	vPosition = vec3( position );
#endif`,Do=`vec3 objectNormal = vec3( normal );
#ifdef USE_TANGENT
	vec3 objectTangent = vec3( tangent.xyz );
#endif`,Io=`float G_BlinnPhong_Implicit( ) {
	return 0.25;
}
float D_BlinnPhong( const in float shininess, const in float dotNH ) {
	return RECIPROCAL_PI * ( shininess * 0.5 + 1.0 ) * pow( dotNH, shininess );
}
vec3 BRDF_BlinnPhong( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in vec3 specularColor, const in float shininess ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( specularColor, 1.0, dotVH );
	float G = G_BlinnPhong_Implicit( );
	float D = D_BlinnPhong( shininess, dotNH );
	return F * ( G * D );
} // validated`,No=`#ifdef USE_IRIDESCENCE
	const mat3 XYZ_TO_REC709 = mat3(
		 3.2404542, -0.9692660,  0.0556434,
		-1.5371385,  1.8760108, -0.2040259,
		-0.4985314,  0.0415560,  1.0572252
	);
	vec3 Fresnel0ToIor( vec3 fresnel0 ) {
		vec3 sqrtF0 = sqrt( fresnel0 );
		return ( vec3( 1.0 ) + sqrtF0 ) / ( vec3( 1.0 ) - sqrtF0 );
	}
	vec3 IorToFresnel0( vec3 transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - vec3( incidentIor ) ) / ( transmittedIor + vec3( incidentIor ) ) );
	}
	float IorToFresnel0( float transmittedIor, float incidentIor ) {
		return pow2( ( transmittedIor - incidentIor ) / ( transmittedIor + incidentIor ));
	}
	vec3 evalSensitivity( float OPD, vec3 shift ) {
		float phase = 2.0 * PI * OPD * 1.0e-9;
		vec3 val = vec3( 5.4856e-13, 4.4201e-13, 5.2481e-13 );
		vec3 pos = vec3( 1.6810e+06, 1.7953e+06, 2.2084e+06 );
		vec3 var = vec3( 4.3278e+09, 9.3046e+09, 6.6121e+09 );
		vec3 xyz = val * sqrt( 2.0 * PI * var ) * cos( pos * phase + shift ) * exp( - pow2( phase ) * var );
		xyz.x += 9.7470e-14 * sqrt( 2.0 * PI * 4.5282e+09 ) * cos( 2.2399e+06 * phase + shift[ 0 ] ) * exp( - 4.5282e+09 * pow2( phase ) );
		xyz /= 1.0685e-7;
		vec3 rgb = XYZ_TO_REC709 * xyz;
		return rgb;
	}
	vec3 evalIridescence( float outsideIOR, float eta2, float cosTheta1, float thinFilmThickness, vec3 baseF0 ) {
		vec3 I;
		float iridescenceIOR = mix( outsideIOR, eta2, smoothstep( 0.0, 0.03, thinFilmThickness ) );
		float sinTheta2Sq = pow2( outsideIOR / iridescenceIOR ) * ( 1.0 - pow2( cosTheta1 ) );
		float cosTheta2Sq = 1.0 - sinTheta2Sq;
		if ( cosTheta2Sq < 0.0 ) {
			return vec3( 1.0 );
		}
		float cosTheta2 = sqrt( cosTheta2Sq );
		float R0 = IorToFresnel0( iridescenceIOR, outsideIOR );
		float R12 = F_Schlick( R0, 1.0, cosTheta1 );
		float T121 = 1.0 - R12;
		float phi12 = 0.0;
		if ( iridescenceIOR < outsideIOR ) phi12 = PI;
		float phi21 = PI - phi12;
		vec3 baseIOR = Fresnel0ToIor( clamp( baseF0, 0.0, 0.9999 ) );		vec3 R1 = IorToFresnel0( baseIOR, iridescenceIOR );
		vec3 R23 = F_Schlick( R1, 1.0, cosTheta2 );
		vec3 phi23 = vec3( 0.0 );
		if ( baseIOR[ 0 ] < iridescenceIOR ) phi23[ 0 ] = PI;
		if ( baseIOR[ 1 ] < iridescenceIOR ) phi23[ 1 ] = PI;
		if ( baseIOR[ 2 ] < iridescenceIOR ) phi23[ 2 ] = PI;
		float OPD = 2.0 * iridescenceIOR * thinFilmThickness * cosTheta2;
		vec3 phi = vec3( phi21 ) + phi23;
		vec3 R123 = clamp( R12 * R23, 1e-5, 0.9999 );
		vec3 r123 = sqrt( R123 );
		vec3 Rs = pow2( T121 ) * R23 / ( vec3( 1.0 ) - R123 );
		vec3 C0 = R12 + Rs;
		I = C0;
		vec3 Cm = Rs - T121;
		for ( int m = 1; m <= 2; ++ m ) {
			Cm *= r123;
			vec3 Sm = 2.0 * evalSensitivity( float( m ) * OPD, float( m ) * phi );
			I += Cm * Sm;
		}
		return max( I, vec3( 0.0 ) );
	}
#endif`,yo=`#ifdef USE_BUMPMAP
	uniform sampler2D bumpMap;
	uniform float bumpScale;
	vec2 dHdxy_fwd() {
		vec2 dSTdx = dFdx( vBumpMapUv );
		vec2 dSTdy = dFdy( vBumpMapUv );
		float Hll = bumpScale * texture2D( bumpMap, vBumpMapUv ).x;
		float dBx = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdx ).x - Hll;
		float dBy = bumpScale * texture2D( bumpMap, vBumpMapUv + dSTdy ).x - Hll;
		return vec2( dBx, dBy );
	}
	vec3 perturbNormalArb( vec3 surf_pos, vec3 surf_norm, vec2 dHdxy, float faceDirection ) {
		vec3 vSigmaX = normalize( dFdx( surf_pos.xyz ) );
		vec3 vSigmaY = normalize( dFdy( surf_pos.xyz ) );
		vec3 vN = surf_norm;
		vec3 R1 = cross( vSigmaY, vN );
		vec3 R2 = cross( vN, vSigmaX );
		float fDet = dot( vSigmaX, R1 ) * faceDirection;
		vec3 vGrad = sign( fDet ) * ( dHdxy.x * R1 + dHdxy.y * R2 );
		return normalize( abs( fDet ) * surf_norm - vGrad );
	}
#endif`,Fo=`#if NUM_CLIPPING_PLANES > 0
	vec4 plane;
	#ifdef ALPHA_TO_COVERAGE
		float distanceToPlane, distanceGradient;
		float clipOpacity = 1.0;
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
			distanceGradient = fwidth( distanceToPlane ) / 2.0;
			clipOpacity *= smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			if ( clipOpacity == 0.0 ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			float unionClipOpacity = 1.0;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				distanceToPlane = - dot( vClipPosition, plane.xyz ) + plane.w;
				distanceGradient = fwidth( distanceToPlane ) / 2.0;
				unionClipOpacity *= 1.0 - smoothstep( - distanceGradient, distanceGradient, distanceToPlane );
			}
			#pragma unroll_loop_end
			clipOpacity *= 1.0 - unionClipOpacity;
		#endif
		diffuseColor.a *= clipOpacity;
		if ( diffuseColor.a == 0.0 ) discard;
	#else
		#pragma unroll_loop_start
		for ( int i = 0; i < UNION_CLIPPING_PLANES; i ++ ) {
			plane = clippingPlanes[ i ];
			if ( dot( vClipPosition, plane.xyz ) > plane.w ) discard;
		}
		#pragma unroll_loop_end
		#if UNION_CLIPPING_PLANES < NUM_CLIPPING_PLANES
			bool clipped = true;
			#pragma unroll_loop_start
			for ( int i = UNION_CLIPPING_PLANES; i < NUM_CLIPPING_PLANES; i ++ ) {
				plane = clippingPlanes[ i ];
				clipped = ( dot( vClipPosition, plane.xyz ) > plane.w ) && clipped;
			}
			#pragma unroll_loop_end
			if ( clipped ) discard;
		#endif
	#endif
#endif`,Oo=`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
	uniform vec4 clippingPlanes[ NUM_CLIPPING_PLANES ];
#endif`,Bo=`#if NUM_CLIPPING_PLANES > 0
	varying vec3 vClipPosition;
#endif`,Go=`#if NUM_CLIPPING_PLANES > 0
	vClipPosition = - mvPosition.xyz;
#endif`,Ho=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	diffuseColor *= vColor;
#endif`,Vo=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA )
	varying vec4 vColor;
#endif`,Wo=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	varying vec4 vColor;
#endif`,ko=`#if defined( USE_COLOR ) || defined( USE_COLOR_ALPHA ) || defined( USE_INSTANCING_COLOR ) || defined( USE_BATCHING_COLOR )
	vColor = vec4( 1.0 );
#endif
#ifdef USE_COLOR_ALPHA
	vColor *= color;
#elif defined( USE_COLOR )
	vColor.rgb *= color;
#endif
#ifdef USE_INSTANCING_COLOR
	vColor.rgb *= instanceColor.rgb;
#endif
#ifdef USE_BATCHING_COLOR
	vColor *= getBatchingColor( getIndirectIndex( gl_DrawID ) );
#endif`,zo=`#define PI 3.141592653589793
#define PI2 6.283185307179586
#define PI_HALF 1.5707963267948966
#define RECIPROCAL_PI 0.3183098861837907
#define RECIPROCAL_PI2 0.15915494309189535
#define EPSILON 1e-6
#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
#define whiteComplement( a ) ( 1.0 - saturate( a ) )
float pow2( const in float x ) { return x*x; }
vec3 pow2( const in vec3 x ) { return x*x; }
float pow3( const in float x ) { return x*x*x; }
float pow4( const in float x ) { float x2 = x*x; return x2*x2; }
float max3( const in vec3 v ) { return max( max( v.x, v.y ), v.z ); }
float average( const in vec3 v ) { return dot( v, vec3( 0.3333333 ) ); }
highp float rand( const in vec2 uv ) {
	const highp float a = 12.9898, b = 78.233, c = 43758.5453;
	highp float dt = dot( uv.xy, vec2( a,b ) ), sn = mod( dt, PI );
	return fract( sin( sn ) * c );
}
#ifdef HIGH_PRECISION
	float precisionSafeLength( vec3 v ) { return length( v ); }
#else
	float precisionSafeLength( vec3 v ) {
		float maxComponent = max3( abs( v ) );
		return length( v / maxComponent ) * maxComponent;
	}
#endif
struct IncidentLight {
	vec3 color;
	vec3 direction;
	bool visible;
};
struct ReflectedLight {
	vec3 directDiffuse;
	vec3 directSpecular;
	vec3 indirectDiffuse;
	vec3 indirectSpecular;
};
#ifdef USE_ALPHAHASH
	varying vec3 vPosition;
#endif
vec3 transformDirection( in vec3 dir, in mat4 matrix ) {
	return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );
}
#define inverseTransformDirection transformDirectionByInverseViewMatrix
vec3 transformNormalByInverseViewMatrix( in vec3 normal, in mat4 viewMatrix ) {
	return normalize( ( vec4( normal, 0.0 ) * viewMatrix ).xyz );
}
vec3 transformDirectionByInverseViewMatrix( in vec3 dir, in mat4 viewMatrix ) {
	return normalize( ( vec4( dir, 0.0 ) * viewMatrix ).xyz );
}
bool isPerspectiveMatrix( mat4 m ) {
	return m[ 2 ][ 3 ] == - 1.0;
}
vec2 equirectUv( in vec3 dir ) {
	float u = atan( dir.z, dir.x ) * RECIPROCAL_PI2 + 0.5;
	float v = asin( clamp( dir.y, - 1.0, 1.0 ) ) * RECIPROCAL_PI + 0.5;
	return vec2( u, v );
}
vec3 BRDF_Lambert( const in vec3 diffuseColor ) {
	return RECIPROCAL_PI * diffuseColor;
}
vec3 F_Schlick( const in vec3 f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
}
float F_Schlick( const in float f0, const in float f90, const in float dotVH ) {
	float fresnel = exp2( ( - 5.55473 * dotVH - 6.98316 ) * dotVH );
	return f0 * ( 1.0 - fresnel ) + ( f90 * fresnel );
} // validated`,Xo=`#ifdef ENVMAP_TYPE_CUBE_UV
	#define cubeUV_minMipLevel 4.0
	#define cubeUV_minTileSize 16.0
	float getFace( vec3 direction ) {
		vec3 absDirection = abs( direction );
		float face = - 1.0;
		if ( absDirection.x > absDirection.z ) {
			if ( absDirection.x > absDirection.y )
				face = direction.x > 0.0 ? 0.0 : 3.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		} else {
			if ( absDirection.z > absDirection.y )
				face = direction.z > 0.0 ? 2.0 : 5.0;
			else
				face = direction.y > 0.0 ? 1.0 : 4.0;
		}
		return face;
	}
	vec2 getUV( vec3 direction, float face ) {
		vec2 uv;
		if ( face == 0.0 ) {
			uv = vec2( direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 1.0 ) {
			uv = vec2( - direction.x, - direction.z ) / abs( direction.y );
		} else if ( face == 2.0 ) {
			uv = vec2( - direction.x, direction.y ) / abs( direction.z );
		} else if ( face == 3.0 ) {
			uv = vec2( - direction.z, direction.y ) / abs( direction.x );
		} else if ( face == 4.0 ) {
			uv = vec2( - direction.x, direction.z ) / abs( direction.y );
		} else {
			uv = vec2( direction.x, direction.y ) / abs( direction.z );
		}
		return 0.5 * ( uv + 1.0 );
	}
	vec3 bilinearCubeUV( sampler2D envMap, vec3 direction, float mipInt ) {
		float face = getFace( direction );
		float filterInt = max( cubeUV_minMipLevel - mipInt, 0.0 );
		mipInt = max( mipInt, cubeUV_minMipLevel );
		float faceSize = exp2( mipInt );
		highp vec2 uv = getUV( direction, face ) * ( faceSize - 2.0 ) + 1.0;
		if ( face > 2.0 ) {
			uv.y += faceSize;
			face -= 3.0;
		}
		uv.x += face * faceSize;
		uv.x += filterInt * 3.0 * cubeUV_minTileSize;
		uv.y += 4.0 * ( exp2( CUBEUV_MAX_MIP ) - faceSize );
		uv.x *= CUBEUV_TEXEL_WIDTH;
		uv.y *= CUBEUV_TEXEL_HEIGHT;
		#ifdef texture2DGradEXT
			return texture2DGradEXT( envMap, uv, vec2( 0.0 ), vec2( 0.0 ) ).rgb;
		#else
			return texture2D( envMap, uv ).rgb;
		#endif
	}
	#define cubeUV_r0 1.0
	#define cubeUV_m0 - 2.0
	#define cubeUV_r1 0.8
	#define cubeUV_m1 - 1.0
	#define cubeUV_r4 0.4
	#define cubeUV_m4 2.0
	#define cubeUV_r5 0.305
	#define cubeUV_m5 3.0
	#define cubeUV_r6 0.21
	#define cubeUV_m6 4.0
	float roughnessToMip( float roughness ) {
		float mip = 0.0;
		if ( roughness >= cubeUV_r1 ) {
			mip = ( cubeUV_r0 - roughness ) * ( cubeUV_m1 - cubeUV_m0 ) / ( cubeUV_r0 - cubeUV_r1 ) + cubeUV_m0;
		} else if ( roughness >= cubeUV_r4 ) {
			mip = ( cubeUV_r1 - roughness ) * ( cubeUV_m4 - cubeUV_m1 ) / ( cubeUV_r1 - cubeUV_r4 ) + cubeUV_m1;
		} else if ( roughness >= cubeUV_r5 ) {
			mip = ( cubeUV_r4 - roughness ) * ( cubeUV_m5 - cubeUV_m4 ) / ( cubeUV_r4 - cubeUV_r5 ) + cubeUV_m4;
		} else if ( roughness >= cubeUV_r6 ) {
			mip = ( cubeUV_r5 - roughness ) * ( cubeUV_m6 - cubeUV_m5 ) / ( cubeUV_r5 - cubeUV_r6 ) + cubeUV_m5;
		} else {
			mip = - 2.0 * log2( 1.16 * roughness );		}
		return mip;
	}
	vec4 textureCubeUV( sampler2D envMap, vec3 sampleDir, float roughness ) {
		float mip = clamp( roughnessToMip( roughness ), cubeUV_m0, CUBEUV_MAX_MIP );
		float mipF = fract( mip );
		float mipInt = floor( mip );
		vec3 color0 = bilinearCubeUV( envMap, sampleDir, mipInt );
		if ( mipF == 0.0 ) {
			return vec4( color0, 1.0 );
		} else {
			vec3 color1 = bilinearCubeUV( envMap, sampleDir, mipInt + 1.0 );
			return vec4( mix( color0, color1, mipF ), 1.0 );
		}
	}
#endif`,Yo=`vec3 transformedNormal = objectNormal;
#ifdef USE_TANGENT
	vec3 transformedTangent = objectTangent;
#endif
#ifdef USE_BATCHING
	mat3 bm = mat3( batchingMatrix );
	transformedNormal /= vec3( dot( bm[ 0 ], bm[ 0 ] ), dot( bm[ 1 ], bm[ 1 ] ), dot( bm[ 2 ], bm[ 2 ] ) );
	transformedNormal = bm * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = bm * transformedTangent;
	#endif
#endif
#ifdef USE_INSTANCING
	mat3 im = mat3( instanceMatrix );
	transformedNormal /= vec3( dot( im[ 0 ], im[ 0 ] ), dot( im[ 1 ], im[ 1 ] ), dot( im[ 2 ], im[ 2 ] ) );
	transformedNormal = im * transformedNormal;
	#ifdef USE_TANGENT
		transformedTangent = im * transformedTangent;
	#endif
#endif
transformedNormal = normalMatrix * transformedNormal;
#ifdef FLIP_SIDED
	transformedNormal = - transformedNormal;
#endif
#ifdef USE_TANGENT
	transformedTangent = ( modelViewMatrix * vec4( transformedTangent, 0.0 ) ).xyz;
#endif`,Ko=`#ifdef USE_DISPLACEMENTMAP
	uniform sampler2D displacementMap;
	uniform float displacementScale;
	uniform float displacementBias;
#endif`,qo=`#ifdef USE_DISPLACEMENTMAP
	transformed += normalize( objectNormal ) * ( texture2D( displacementMap, vDisplacementMapUv ).x * displacementScale + displacementBias );
#endif`,Zo=`#ifdef USE_EMISSIVEMAP
	vec4 emissiveColor = texture2D( emissiveMap, vEmissiveMapUv );
	#ifdef DECODE_VIDEO_TEXTURE_EMISSIVE
		emissiveColor = sRGBTransferEOTF( emissiveColor );
	#endif
	totalEmissiveRadiance *= emissiveColor.rgb;
#endif`,$o=`#ifdef USE_EMISSIVEMAP
	uniform sampler2D emissiveMap;
#endif`,Qo="gl_FragColor = linearToOutputTexel( gl_FragColor );",Jo=`vec4 LinearTransferOETF( in vec4 value ) {
	return value;
}
vec4 sRGBTransferEOTF( in vec4 value ) {
	return vec4( mix( pow( value.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), value.rgb * 0.0773993808, vec3( lessThanEqual( value.rgb, vec3( 0.04045 ) ) ) ), value.a );
}
vec4 sRGBTransferOETF( in vec4 value ) {
	return vec4( mix( pow( value.rgb, vec3( 0.41666 ) ) * 1.055 - vec3( 0.055 ), value.rgb * 12.92, vec3( lessThanEqual( value.rgb, vec3( 0.0031308 ) ) ) ), value.a );
}`,jo=`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vec3 cameraToFrag;
		if ( isOrthographic ) {
			cameraToFrag = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToFrag = normalize( vWorldPosition - cameraPosition );
		}
		vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vec3 reflectVec = reflect( cameraToFrag, worldNormal );
		#else
			vec3 reflectVec = refract( cameraToFrag, worldNormal, refractionRatio );
		#endif
	#else
		vec3 reflectVec = vReflect;
	#endif
	#ifdef ENVMAP_TYPE_CUBE
		vec4 envColor = textureCube( envMap, envMapRotation * reflectVec );
		#ifdef ENVMAP_BLENDING_MULTIPLY
			outgoingLight = mix( outgoingLight, outgoingLight * envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_MIX )
			outgoingLight = mix( outgoingLight, envColor.xyz, specularStrength * reflectivity );
		#elif defined( ENVMAP_BLENDING_ADD )
			outgoingLight += envColor.xyz * specularStrength * reflectivity;
		#endif
	#endif
#endif`,es=`#ifdef USE_ENVMAP
	uniform float envMapIntensity;
	uniform mat3 envMapRotation;
	#ifdef ENVMAP_TYPE_CUBE
		uniform samplerCube envMap;
	#else
		uniform sampler2D envMap;
	#endif
#endif`,ts=`#ifdef USE_ENVMAP
	uniform float reflectivity;
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		varying vec3 vWorldPosition;
		uniform float refractionRatio;
	#else
		varying vec3 vReflect;
	#endif
#endif`,ns=`#ifdef USE_ENVMAP
	#if defined( USE_BUMPMAP ) || defined( USE_NORMALMAP ) || defined( PHONG ) || defined( LAMBERT )
		#define ENV_WORLDPOS
	#endif
	#ifdef ENV_WORLDPOS
		
		varying vec3 vWorldPosition;
	#else
		varying vec3 vReflect;
		uniform float refractionRatio;
	#endif
#endif`,is=`#ifdef USE_ENVMAP
	#ifdef ENV_WORLDPOS
		vWorldPosition = worldPosition.xyz;
	#else
		vec3 cameraToVertex;
		if ( isOrthographic ) {
			cameraToVertex = normalize( vec3( - viewMatrix[ 0 ][ 2 ], - viewMatrix[ 1 ][ 2 ], - viewMatrix[ 2 ][ 2 ] ) );
		} else {
			cameraToVertex = normalize( worldPosition.xyz - cameraPosition );
		}
		vec3 worldNormal = transformNormalByInverseViewMatrix( transformedNormal, viewMatrix );
		#ifdef ENVMAP_MODE_REFLECTION
			vReflect = reflect( cameraToVertex, worldNormal );
		#else
			vReflect = refract( cameraToVertex, worldNormal, refractionRatio );
		#endif
	#endif
#endif`,rs=`#ifdef USE_FOG
	vFogDepth = - mvPosition.z;
#endif`,as=`#ifdef USE_FOG
	varying float vFogDepth;
#endif`,os=`#ifdef USE_FOG
	#ifdef FOG_EXP2
		float fogFactor = 1.0 - exp( - fogDensity * fogDensity * vFogDepth * vFogDepth );
	#else
		float fogFactor = smoothstep( fogNear, fogFar, vFogDepth );
	#endif
	gl_FragColor.rgb = mix( gl_FragColor.rgb, fogColor, fogFactor );
#endif`,ss=`#ifdef USE_FOG
	uniform vec3 fogColor;
	varying float vFogDepth;
	#ifdef FOG_EXP2
		uniform float fogDensity;
	#else
		uniform float fogNear;
		uniform float fogFar;
	#endif
#endif`,ls=`#ifdef USE_GRADIENTMAP
	uniform sampler2D gradientMap;
#endif
vec3 getGradientIrradiance( vec3 normal, vec3 lightDirection ) {
	float dotNL = dot( normal, lightDirection );
	vec2 coord = vec2( dotNL * 0.5 + 0.5, 0.0 );
	#ifdef USE_GRADIENTMAP
		return vec3( texture2D( gradientMap, coord ).r );
	#else
		vec2 fw = fwidth( coord ) * 0.5;
		return mix( vec3( 0.7 ), vec3( 1.0 ), smoothstep( 0.7 - fw.x, 0.7 + fw.x, coord.x ) );
	#endif
}`,cs=`#ifdef USE_LIGHTMAP
	uniform sampler2D lightMap;
	uniform float lightMapIntensity;
#endif`,fs=`LambertMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularStrength = specularStrength;`,ds=`varying vec3 vViewPosition;
struct LambertMaterial {
	vec3 diffuseColor;
	float specularStrength;
};
void RE_Direct_Lambert( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Lambert( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in LambertMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Lambert
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Lambert`,us=`uniform bool receiveShadow;
uniform vec3 ambientLightColor;
#if defined( USE_LIGHT_PROBES )
	uniform vec3 lightProbe[ 9 ];
#endif
vec3 shGetIrradianceAt( in vec3 normal, in vec3 shCoefficients[ 9 ] ) {
	float x = normal.x, y = normal.y, z = normal.z;
	vec3 result = shCoefficients[ 0 ] * 0.886227;
	result += shCoefficients[ 1 ] * 2.0 * 0.511664 * y;
	result += shCoefficients[ 2 ] * 2.0 * 0.511664 * z;
	result += shCoefficients[ 3 ] * 2.0 * 0.511664 * x;
	result += shCoefficients[ 4 ] * 2.0 * 0.429043 * x * y;
	result += shCoefficients[ 5 ] * 2.0 * 0.429043 * y * z;
	result += shCoefficients[ 6 ] * ( 0.743125 * z * z - 0.247708 );
	result += shCoefficients[ 7 ] * 2.0 * 0.429043 * x * z;
	result += shCoefficients[ 8 ] * 0.429043 * ( x * x - y * y );
	return result;
}
vec3 getLightProbeIrradiance( const in vec3 lightProbe[ 9 ], const in vec3 normal ) {
	vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
	vec3 irradiance = shGetIrradianceAt( worldNormal, lightProbe );
	return irradiance;
}
vec3 getAmbientLightIrradiance( const in vec3 ambientLightColor ) {
	vec3 irradiance = ambientLightColor;
	return irradiance;
}
float getDistanceAttenuation( const in float lightDistance, const in float cutoffDistance, const in float decayExponent ) {
	float distanceFalloff = 1.0 / max( pow( lightDistance, decayExponent ), 0.01 );
	if ( cutoffDistance > 0.0 ) {
		distanceFalloff *= pow2( saturate( 1.0 - pow4( lightDistance / cutoffDistance ) ) );
	}
	return distanceFalloff;
}
float getSpotAttenuation( const in float coneCosine, const in float penumbraCosine, const in float angleCosine ) {
	return smoothstep( coneCosine, penumbraCosine, angleCosine );
}
#if NUM_SUN_LIGHTS > 0
	struct SunLight {
		vec3 direction;
		vec3 color;
	};
	uniform SunLight sunLights[ NUM_SUN_LIGHTS ];
	void getSunLightInfo( const in SunLight sunLight, out IncidentLight light ) {
		light.color = sunLight.color;
		light.direction = sunLight.direction;
		light.visible = true;
	}
#endif
#if NUM_DIR_LIGHTS > 0
	struct DirectionalLight {
		vec3 direction;
		vec3 color;
	};
	uniform DirectionalLight directionalLights[ NUM_DIR_LIGHTS ];
	void getDirectionalLightInfo( const in DirectionalLight directionalLight, out IncidentLight light ) {
		light.color = directionalLight.color;
		light.direction = directionalLight.direction;
		light.visible = true;
	}
#endif
#if NUM_POINT_LIGHTS > 0
	struct PointLight {
		vec3 position;
		vec3 color;
		float distance;
		float decay;
	};
	uniform PointLight pointLights[ NUM_POINT_LIGHTS ];
	void getPointLightInfo( const in PointLight pointLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = pointLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float lightDistance = length( lVector );
		light.color = pointLight.color;
		light.color *= getDistanceAttenuation( lightDistance, pointLight.distance, pointLight.decay );
		light.visible = ( light.color != vec3( 0.0 ) );
	}
#endif
#if NUM_SPOT_LIGHTS > 0
	struct SpotLight {
		vec3 position;
		vec3 direction;
		vec3 color;
		float distance;
		float decay;
		float coneCos;
		float penumbraCos;
	};
	uniform SpotLight spotLights[ NUM_SPOT_LIGHTS ];
	void getSpotLightInfo( const in SpotLight spotLight, const in vec3 geometryPosition, out IncidentLight light ) {
		vec3 lVector = spotLight.position - geometryPosition;
		light.direction = normalize( lVector );
		float angleCos = dot( light.direction, spotLight.direction );
		float spotAttenuation = getSpotAttenuation( spotLight.coneCos, spotLight.penumbraCos, angleCos );
		if ( spotAttenuation > 0.0 ) {
			float lightDistance = length( lVector );
			light.color = spotLight.color * spotAttenuation;
			light.color *= getDistanceAttenuation( lightDistance, spotLight.distance, spotLight.decay );
			light.visible = ( light.color != vec3( 0.0 ) );
		} else {
			light.color = vec3( 0.0 );
			light.visible = false;
		}
	}
#endif
#if NUM_RECT_AREA_LIGHTS > 0
	struct RectAreaLight {
		vec3 color;
		vec3 position;
		vec3 halfWidth;
		vec3 halfHeight;
	};
	uniform sampler2D ltc_1;	uniform sampler2D ltc_2;
	uniform RectAreaLight rectAreaLights[ NUM_RECT_AREA_LIGHTS ];
#endif
#if NUM_HEMI_LIGHTS > 0
	struct HemisphereLight {
		vec3 direction;
		vec3 skyColor;
		vec3 groundColor;
	};
	uniform HemisphereLight hemisphereLights[ NUM_HEMI_LIGHTS ];
	vec3 getHemisphereLightIrradiance( const in HemisphereLight hemiLight, const in vec3 normal ) {
		float dotNL = dot( normal, hemiLight.direction );
		float hemiDiffuseWeight = 0.5 * dotNL + 0.5;
		vec3 irradiance = mix( hemiLight.groundColor, hemiLight.skyColor, hemiDiffuseWeight );
		return irradiance;
	}
#endif
#include <lightprobes_pars_fragment>`,ps=`#ifdef USE_ENVMAP
	vec3 getIBLIrradiance( const in vec3 normal ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 worldNormal = transformNormalByInverseViewMatrix( normal, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * worldNormal, 1.0 );
			return PI * envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	vec3 getIBLRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness ) {
		#ifdef ENVMAP_TYPE_CUBE_UV
			vec3 reflectVec = reflect( - viewDir, normal );
			reflectVec = normalize( mix( reflectVec, normal, pow4( roughness ) ) );
			reflectVec = transformDirectionByInverseViewMatrix( reflectVec, viewMatrix );
			vec4 envMapColor = textureCubeUV( envMap, envMapRotation * reflectVec, roughness );
			return envMapColor.rgb * envMapIntensity;
		#else
			return vec3( 0.0 );
		#endif
	}
	#ifdef USE_RETROREFLECTION
		vec3 getIBLRetroRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness ) {
			#ifdef ENVMAP_TYPE_CUBE_UV
				vec3 retroVec = normalize( mix( viewDir, normal, pow4( roughness ) ) );
				retroVec = transformDirectionByInverseViewMatrix( retroVec, viewMatrix );
				vec4 envMapColor = textureCubeUV( envMap, envMapRotation * retroVec, roughness );
				return envMapColor.rgb * envMapIntensity;
			#else
				return vec3( 0.0 );
			#endif
		}
	#endif
	#ifdef USE_ANISOTROPY
		vec3 getIBLAnisotropyRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness, const in vec3 bitangent, const in float anisotropy ) {
			#ifdef ENVMAP_TYPE_CUBE_UV
				vec3 bentNormal = cross( bitangent, viewDir );
				bentNormal = normalize( cross( bentNormal, bitangent ) );
				bentNormal = normalize( mix( bentNormal, normal, pow2( pow2( 1.0 - anisotropy * ( 1.0 - roughness ) ) ) ) );
				return getIBLRadiance( viewDir, bentNormal, roughness );
			#else
				return vec3( 0.0 );
			#endif
		}
		#ifdef USE_RETROREFLECTION
			vec3 getIBLAnisotropyRetroRadiance( const in vec3 viewDir, const in vec3 normal, const in float roughness, const in vec3 bitangent, const in float anisotropy ) {
				#ifdef ENVMAP_TYPE_CUBE_UV
					vec3 bentNormal = cross( bitangent, viewDir );
					bentNormal = normalize( cross( bentNormal, bitangent ) );
					bentNormal = normalize( mix( bentNormal, normal, pow2( pow2( 1.0 - anisotropy * ( 1.0 - roughness ) ) ) ) );
					return getIBLRetroRadiance( viewDir, bentNormal, roughness );
				#else
					return vec3( 0.0 );
				#endif
			}
		#endif
	#endif
#endif`,hs=`ToonMaterial material;
material.diffuseColor = diffuseColor.rgb;`,ms=`varying vec3 vViewPosition;
struct ToonMaterial {
	vec3 diffuseColor;
};
void RE_Direct_Toon( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 irradiance = getGradientIrradiance( geometryNormal, directLight.direction ) * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
void RE_IndirectDiffuse_Toon( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in ToonMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_Toon
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Toon`,_s=`BlinnPhongMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.specularColor = specular;
material.specularShininess = shininess;
material.specularStrength = specularStrength;`,gs=`varying vec3 vViewPosition;
struct BlinnPhongMaterial {
	vec3 diffuseColor;
	vec3 specularColor;
	float specularShininess;
	float specularStrength;
};
void RE_Direct_BlinnPhong( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
	reflectedLight.directSpecular += irradiance * BRDF_BlinnPhong( directLight.direction, geometryViewDir, geometryNormal, material.specularColor, material.specularShininess ) * material.specularStrength;
}
void RE_IndirectDiffuse_BlinnPhong( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in BlinnPhongMaterial material, inout ReflectedLight reflectedLight ) {
	reflectedLight.indirectDiffuse += irradiance * BRDF_Lambert( material.diffuseColor );
}
#define RE_Direct				RE_Direct_BlinnPhong
#define RE_IndirectDiffuse		RE_IndirectDiffuse_BlinnPhong`,vs=`PhysicalMaterial material;
material.diffuseColor = diffuseColor.rgb;
material.diffuseContribution = diffuseColor.rgb * ( 1.0 - metalnessFactor );
material.metalness = metalnessFactor;
vec3 dxy = max( abs( dFdx( nonPerturbedNormal ) ), abs( dFdy( nonPerturbedNormal ) ) );
float geometryRoughness = max( max( dxy.x, dxy.y ), dxy.z );
material.roughness = max( roughnessFactor, 0.0525 );material.roughness += geometryRoughness;
material.roughness = min( material.roughness, 1.0 );
#ifdef IOR
	material.ior = ior;
	#ifdef USE_SPECULAR
		float specularIntensityFactor = specularIntensity;
		vec3 specularColorFactor = specularColor;
		#ifdef USE_SPECULAR_COLORMAP
			specularColorFactor *= texture2D( specularColorMap, vSpecularColorMapUv ).rgb;
		#endif
		#ifdef USE_SPECULAR_INTENSITYMAP
			specularIntensityFactor *= texture2D( specularIntensityMap, vSpecularIntensityMapUv ).a;
		#endif
		material.specularF90 = mix( specularIntensityFactor, 1.0, metalnessFactor );
	#else
		float specularIntensityFactor = 1.0;
		vec3 specularColorFactor = vec3( 1.0 );
		material.specularF90 = 1.0;
	#endif
	material.specularColor = min( pow2( ( material.ior - 1.0 ) / ( material.ior + 1.0 ) ) * specularColorFactor, vec3( 1.0 ) ) * specularIntensityFactor;
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
#else
	material.specularColor = vec3( 0.04 );
	material.specularColorBlended = mix( material.specularColor, diffuseColor.rgb, metalnessFactor );
	material.specularF90 = 1.0;
#endif
#ifdef USE_CLEARCOAT
	material.clearcoat = clearcoat;
	material.clearcoatRoughness = clearcoatRoughness;
	material.clearcoatF0 = vec3( 0.04 );
	material.clearcoatF90 = 1.0;
	#ifdef USE_CLEARCOATMAP
		material.clearcoat *= texture2D( clearcoatMap, vClearcoatMapUv ).x;
	#endif
	#ifdef USE_CLEARCOAT_ROUGHNESSMAP
		material.clearcoatRoughness *= texture2D( clearcoatRoughnessMap, vClearcoatRoughnessMapUv ).y;
	#endif
	material.clearcoat = saturate( material.clearcoat );	material.clearcoatRoughness = max( material.clearcoatRoughness, 0.0525 );
	material.clearcoatRoughness += geometryRoughness;
	material.clearcoatRoughness = min( material.clearcoatRoughness, 1.0 );
#endif
#ifdef USE_DISPERSION
	material.dispersion = dispersion;
#endif
#ifdef USE_RETROREFLECTION
	material.retroreflectivity = retroreflectivity;
#endif
#ifdef USE_IRIDESCENCE
	material.iridescence = iridescence;
	material.iridescenceIOR = iridescenceIOR;
	#ifdef USE_IRIDESCENCEMAP
		material.iridescence *= texture2D( iridescenceMap, vIridescenceMapUv ).r;
	#endif
	#ifdef USE_IRIDESCENCE_THICKNESSMAP
		material.iridescenceThickness = (iridescenceThicknessMaximum - iridescenceThicknessMinimum) * texture2D( iridescenceThicknessMap, vIridescenceThicknessMapUv ).g + iridescenceThicknessMinimum;
	#else
		material.iridescenceThickness = iridescenceThicknessMaximum;
	#endif
#endif
#ifdef USE_SHEEN
	material.sheenColor = sheenColor;
	#ifdef USE_SHEEN_COLORMAP
		material.sheenColor *= texture2D( sheenColorMap, vSheenColorMapUv ).rgb;
	#endif
	material.sheenRoughness = clamp( sheenRoughness, 0.0001, 1.0 );
	#ifdef USE_SHEEN_ROUGHNESSMAP
		material.sheenRoughness *= texture2D( sheenRoughnessMap, vSheenRoughnessMapUv ).a;
	#endif
#endif
#ifdef USE_ANISOTROPY
	#ifdef USE_ANISOTROPYMAP
		mat2 anisotropyMat = mat2( anisotropyVector.x, anisotropyVector.y, - anisotropyVector.y, anisotropyVector.x );
		vec3 anisotropyPolar = texture2D( anisotropyMap, vAnisotropyMapUv ).rgb;
		vec2 anisotropyV = anisotropyMat * normalize( 2.0 * anisotropyPolar.rg - vec2( 1.0 ) ) * anisotropyPolar.b;
	#else
		vec2 anisotropyV = anisotropyVector;
	#endif
	material.anisotropy = length( anisotropyV );
	if( material.anisotropy == 0.0 ) {
		anisotropyV = vec2( 1.0, 0.0 );
	} else {
		anisotropyV /= material.anisotropy;
		material.anisotropy = saturate( material.anisotropy );
	}
	material.alphaT = mix( pow2( material.roughness ), 1.0, pow2( material.anisotropy ) );
	material.anisotropyT = tbn[ 0 ] * anisotropyV.x + tbn[ 1 ] * anisotropyV.y;
	material.anisotropyB = tbn[ 1 ] * anisotropyV.x - tbn[ 0 ] * anisotropyV.y;
#endif`,Ss=`uniform sampler2D dfgLUT;
struct PhysicalMaterial {
	vec3 diffuseColor;
	vec3 diffuseContribution;
	vec3 specularColor;
	vec3 specularColorBlended;
	float roughness;
	float metalness;
	float specularF90;
	float dispersion;
	vec2 dfg;
	vec3 multiScatteringCompensation;
	#ifdef USE_RETROREFLECTION
		float retroreflectivity;
	#endif
	#ifdef USE_CLEARCOAT
		float clearcoat;
		float clearcoatRoughness;
		vec3 clearcoatF0;
		float clearcoatF90;
	#endif
	#ifdef USE_IRIDESCENCE
		float iridescence;
		float iridescenceIOR;
		float iridescenceThickness;
		vec3 iridescenceFresnel;
		vec3 iridescenceF0Dielectric;
		vec3 iridescenceF0Metallic;
	#endif
	#ifdef USE_SHEEN
		vec3 sheenColor;
		float sheenRoughness;
	#endif
	#ifdef IOR
		float ior;
	#endif
	#ifdef USE_TRANSMISSION
		float transmission;
		float transmissionAlpha;
		float thickness;
		float attenuationDistance;
		vec3 attenuationColor;
	#endif
	#ifdef USE_ANISOTROPY
		float anisotropy;
		float alphaT;
		vec3 anisotropyT;
		vec3 anisotropyB;
	#endif
};
vec3 clearcoatSpecularDirect = vec3( 0.0 );
vec3 clearcoatSpecularIndirect = vec3( 0.0 );
vec3 sheenSpecularDirect = vec3( 0.0 );
vec3 sheenSpecularIndirect = vec3(0.0 );
vec3 Schlick_to_F0( const in vec3 f, const in float f90, const in float dotVH ) {
    float x = clamp( 1.0 - dotVH, 0.0, 1.0 );
    float x2 = x * x;
    float x5 = clamp( x * x2 * x2, 0.0, 0.9999 );
    return ( f - vec3( f90 ) * x5 ) / ( 1.0 - x5 );
}
float V_GGX_SmithCorrelated( const in float alpha, const in float dotNL, const in float dotNV ) {
	float a2 = pow2( alpha );
	float gv = dotNL * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNV ) );
	float gl = dotNV * sqrt( a2 + ( 1.0 - a2 ) * pow2( dotNL ) );
	return 0.5 / max( gv + gl, EPSILON );
}
float D_GGX( const in float alpha, const in float dotNH ) {
	float a2 = pow2( alpha );
	float denom = pow2( dotNH ) * ( a2 - 1.0 ) + 1.0;
	return RECIPROCAL_PI * a2 / pow2( denom );
}
#ifdef USE_ANISOTROPY
	float V_GGX_SmithCorrelated_Anisotropic( const in float alphaT, const in float alphaB, const in float dotTV, const in float dotBV, const in float dotTL, const in float dotBL, const in float dotNV, const in float dotNL ) {
		float gv = dotNL * length( vec3( alphaT * dotTV, alphaB * dotBV, dotNV ) );
		float gl = dotNV * length( vec3( alphaT * dotTL, alphaB * dotBL, dotNL ) );
		return 0.5 / max( gv + gl, EPSILON );
	}
	float D_GGX_Anisotropic( const in float alphaT, const in float alphaB, const in float dotNH, const in float dotTH, const in float dotBH ) {
		float a2 = alphaT * alphaB;
		highp vec3 v = vec3( alphaB * dotTH, alphaT * dotBH, a2 * dotNH );
		highp float v2 = dot( v, v );
		float w2 = a2 / v2;
		return RECIPROCAL_PI * a2 * pow2 ( w2 );
	}
#endif
#ifdef USE_CLEARCOAT
	vec3 BRDF_GGX_Clearcoat( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material) {
		vec3 f0 = material.clearcoatF0;
		float f90 = material.clearcoatF90;
		float roughness = material.clearcoatRoughness;
		float alpha = pow2( roughness );
		vec3 halfDir = normalize( lightDir + viewDir );
		float dotNL = saturate( dot( normal, lightDir ) );
		float dotNV = saturate( dot( normal, viewDir ) );
		float dotNH = saturate( dot( normal, halfDir ) );
		float dotVH = saturate( dot( viewDir, halfDir ) );
		vec3 F = F_Schlick( f0, f90, dotVH );
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
		return F * ( V * D );
	}
#endif
vec3 BRDF_GGX( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, const in PhysicalMaterial material ) {
	vec3 f0 = material.specularColorBlended;
	float f90 = material.specularF90;
	float roughness = material.roughness;
	float alpha = pow2( roughness );
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float dotVH = saturate( dot( viewDir, halfDir ) );
	vec3 F = F_Schlick( f0, f90, dotVH );
	#ifdef USE_IRIDESCENCE
		F = mix( F, material.iridescenceFresnel, material.iridescence );
	#endif
	#ifdef USE_ANISOTROPY
		float dotTL = dot( material.anisotropyT, lightDir );
		float dotTV = dot( material.anisotropyT, viewDir );
		float dotTH = dot( material.anisotropyT, halfDir );
		float dotBL = dot( material.anisotropyB, lightDir );
		float dotBV = dot( material.anisotropyB, viewDir );
		float dotBH = dot( material.anisotropyB, halfDir );
		float V = V_GGX_SmithCorrelated_Anisotropic( material.alphaT, alpha, dotTV, dotBV, dotTL, dotBL, dotNV, dotNL );
		float D = D_GGX_Anisotropic( material.alphaT, alpha, dotNH, dotTH, dotBH );
	#else
		float V = V_GGX_SmithCorrelated( alpha, dotNL, dotNV );
		float D = D_GGX( alpha, dotNH );
	#endif
	return F * ( V * D );
}
vec2 LTC_Uv( const in vec3 N, const in vec3 V, const in float roughness ) {
	const float LUT_SIZE = 64.0;
	const float LUT_SCALE = ( LUT_SIZE - 1.0 ) / LUT_SIZE;
	const float LUT_BIAS = 0.5 / LUT_SIZE;
	float dotNV = saturate( dot( N, V ) );
	vec2 uv = vec2( roughness, sqrt( 1.0 - dotNV ) );
	uv = uv * LUT_SCALE + LUT_BIAS;
	return uv;
}
float LTC_ClippedSphereFormFactor( const in vec3 f ) {
	float l = length( f );
	return max( ( l * l + f.z ) / ( l + 1.0 ), 0.0 );
}
vec3 LTC_EdgeVectorFormFactor( const in vec3 v1, const in vec3 v2 ) {
	float x = dot( v1, v2 );
	float y = abs( x );
	float a = 0.8543985 + ( 0.4965155 + 0.0145206 * y ) * y;
	float b = 3.4175940 + ( 4.1616724 + y ) * y;
	float v = a / b;
	float theta_sintheta = ( x > 0.0 ) ? v : 0.5 * inversesqrt( max( 1.0 - x * x, 1e-7 ) ) - v;
	return cross( v1, v2 ) * theta_sintheta;
}
vec3 LTC_Evaluate( const in vec3 N, const in vec3 V, const in vec3 P, const in mat3 mInv, const in vec3 rectCoords[ 4 ] ) {
	vec3 v1 = rectCoords[ 1 ] - rectCoords[ 0 ];
	vec3 v2 = rectCoords[ 3 ] - rectCoords[ 0 ];
	vec3 lightNormal = cross( v1, v2 );
	if( dot( lightNormal, P - rectCoords[ 0 ] ) < 0.0 ) return vec3( 0.0 );
	vec3 T1, T2;
	T1 = normalize( V - N * dot( V, N ) );
	T2 = - cross( N, T1 );
	mat3 mat = mInv * transpose( mat3( T1, T2, N ) );
	vec3 coords[ 4 ];
	coords[ 0 ] = mat * ( rectCoords[ 0 ] - P );
	coords[ 1 ] = mat * ( rectCoords[ 1 ] - P );
	coords[ 2 ] = mat * ( rectCoords[ 2 ] - P );
	coords[ 3 ] = mat * ( rectCoords[ 3 ] - P );
	coords[ 0 ] = normalize( coords[ 0 ] );
	coords[ 1 ] = normalize( coords[ 1 ] );
	coords[ 2 ] = normalize( coords[ 2 ] );
	coords[ 3 ] = normalize( coords[ 3 ] );
	vec3 vectorFormFactor = vec3( 0.0 );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 0 ], coords[ 1 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 1 ], coords[ 2 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 2 ], coords[ 3 ] );
	vectorFormFactor += LTC_EdgeVectorFormFactor( coords[ 3 ], coords[ 0 ] );
	float result = LTC_ClippedSphereFormFactor( vectorFormFactor );
	return vec3( result );
}
#if defined( USE_SHEEN )
float D_Charlie( float roughness, float dotNH ) {
	float alpha = pow2( roughness );
	float invAlpha = 1.0 / alpha;
	float cos2h = dotNH * dotNH;
	float sin2h = max( 1.0 - cos2h, 0.0078125 );
	return ( 2.0 + invAlpha ) * pow( sin2h, invAlpha * 0.5 ) / ( 2.0 * PI );
}
float V_Neubelt( float dotNV, float dotNL ) {
	return saturate( 1.0 / ( 4.0 * ( dotNL + dotNV - dotNL * dotNV ) ) );
}
vec3 BRDF_Sheen( const in vec3 lightDir, const in vec3 viewDir, const in vec3 normal, vec3 sheenColor, const in float sheenRoughness ) {
	vec3 halfDir = normalize( lightDir + viewDir );
	float dotNL = saturate( dot( normal, lightDir ) );
	float dotNV = saturate( dot( normal, viewDir ) );
	float dotNH = saturate( dot( normal, halfDir ) );
	float D = D_Charlie( sheenRoughness, dotNH );
	float V = V_Neubelt( dotNV, dotNL );
	return sheenColor * ( D * V );
}
#endif
float IBLSheenBRDF( const in vec3 normal, const in vec3 viewDir, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	float r2 = roughness * roughness;
	float rInv = 1.0 / ( roughness + 0.1 );
	float a = -1.9362 + 1.0678 * roughness + 0.4573 * r2 - 0.8469 * rInv;
	float b = -0.6014 + 0.5538 * roughness - 0.4670 * r2 - 0.1255 * rInv;
	float DG = exp( a * dotNV + b );
	return saturate( DG );
}
vec3 EnvironmentBRDF( const in vec3 normal, const in vec3 viewDir, const in vec3 specularColor, const in float specularF90, const in float roughness ) {
	float dotNV = saturate( dot( normal, viewDir ) );
	vec2 fab = texture2D( dfgLUT, vec2( roughness, dotNV ) ).rg;
	return specularColor * fab.x + specularF90 * fab.y;
}
#ifdef USE_IRIDESCENCE
void computeMultiscatteringIridescence( const in vec2 fab, const in vec3 specularColor, const in float specularF90, const in float iridescence, const in vec3 iridescenceF0, inout vec3 singleScatter, inout vec3 multiScatter ) {
#else
void computeMultiscattering( const in vec2 fab, const in vec3 specularColor, const in float specularF90, inout vec3 singleScatter, inout vec3 multiScatter ) {
#endif
	#ifdef USE_IRIDESCENCE
		vec3 Fr = mix( specularColor, iridescenceF0, iridescence );
	#else
		vec3 Fr = specularColor;
	#endif
	vec3 FssEss = Fr * fab.x + specularF90 * fab.y;
	float Ess = fab.x + fab.y;
	float Ems = 1.0 - Ess;
	vec3 Favg = Fr + ( 1.0 - Fr ) * 0.047619;	vec3 Fms = FssEss * Favg / ( 1.0 - Ems * Favg );
	singleScatter += FssEss;
	multiScatter += Fms * Ems;
}
#if NUM_RECT_AREA_LIGHTS > 0
	void RE_Direct_RectArea_Physical( const in RectAreaLight rectAreaLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
		vec3 normal = geometryNormal;
		vec3 viewDir = geometryViewDir;
		vec3 position = geometryPosition;
		vec3 lightPos = rectAreaLight.position;
		vec3 halfWidth = rectAreaLight.halfWidth;
		vec3 halfHeight = rectAreaLight.halfHeight;
		vec3 lightColor = rectAreaLight.color;
		float roughness = material.roughness;
		vec3 rectCoords[ 4 ];
		rectCoords[ 0 ] = lightPos + halfWidth - halfHeight;		rectCoords[ 1 ] = lightPos - halfWidth - halfHeight;
		rectCoords[ 2 ] = lightPos - halfWidth + halfHeight;
		rectCoords[ 3 ] = lightPos + halfWidth + halfHeight;
		vec2 uv = LTC_Uv( normal, viewDir, roughness );
		vec4 t1 = texture2D( ltc_1, uv );
		vec4 t2 = texture2D( ltc_2, uv );
		mat3 mInv = mat3(
			vec3( t1.x, 0, t1.y ),
			vec3(    0, 1,    0 ),
			vec3( t1.z, 0, t1.w )
		);
		vec3 fresnel = ( material.specularColorBlended * t2.x + ( material.specularF90 - material.specularColorBlended ) * t2.y );
		reflectedLight.directSpecular += lightColor * fresnel * LTC_Evaluate( normal, viewDir, position, mInv, rectCoords );
		reflectedLight.directDiffuse += lightColor * material.diffuseContribution * LTC_Evaluate( normal, viewDir, position, mat3( 1.0 ), rectCoords );
		#ifdef USE_CLEARCOAT
			vec3 Ncc = geometryClearcoatNormal;
			vec2 uvClearcoat = LTC_Uv( Ncc, viewDir, material.clearcoatRoughness );
			vec4 t1Clearcoat = texture2D( ltc_1, uvClearcoat );
			vec4 t2Clearcoat = texture2D( ltc_2, uvClearcoat );
			mat3 mInvClearcoat = mat3(
				vec3( t1Clearcoat.x, 0, t1Clearcoat.y ),
				vec3(             0, 1,             0 ),
				vec3( t1Clearcoat.z, 0, t1Clearcoat.w )
			);
			vec3 fresnelClearcoat = material.clearcoatF0 * t2Clearcoat.x + ( material.clearcoatF90 - material.clearcoatF0 ) * t2Clearcoat.y;
			clearcoatSpecularDirect += lightColor * fresnelClearcoat * LTC_Evaluate( Ncc, viewDir, position, mInvClearcoat, rectCoords );
		#endif
	}
#endif
void RE_Direct_Physical( const in IncidentLight directLight, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	float dotNL = saturate( dot( geometryNormal, directLight.direction ) );
	vec3 irradiance = dotNL * directLight.color;
	#ifdef USE_CLEARCOAT
		float dotNLcc = saturate( dot( geometryClearcoatNormal, directLight.direction ) );
		vec3 ccIrradiance = dotNLcc * directLight.color;
		clearcoatSpecularDirect += ccIrradiance * BRDF_GGX_Clearcoat( directLight.direction, geometryViewDir, geometryClearcoatNormal, material );
	#endif
	#ifdef USE_SHEEN
 
 		sheenSpecularDirect += irradiance * BRDF_Sheen( directLight.direction, geometryViewDir, geometryNormal, material.sheenColor, material.sheenRoughness );
 
 		float sheenAlbedoV = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
 		float sheenAlbedoL = IBLSheenBRDF( geometryNormal, directLight.direction, material.sheenRoughness );
 
 		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * max( sheenAlbedoV, sheenAlbedoL );
 
 		irradiance *= sheenEnergyComp;
 
 	#endif
	vec3 specularBRDF = BRDF_GGX( directLight.direction, geometryViewDir, geometryNormal, material );
	#ifdef USE_RETROREFLECTION
		vec3 retroViewDir = reflect( - geometryViewDir, geometryNormal );
		vec3 retroSpecularBRDF = BRDF_GGX( directLight.direction, retroViewDir, geometryNormal, material );
		specularBRDF = mix( specularBRDF, retroSpecularBRDF, saturate( material.retroreflectivity ) );
	#endif
	reflectedLight.directSpecular += irradiance * specularBRDF * material.multiScatteringCompensation;
	vec3 halfDir = normalize( directLight.direction + geometryViewDir );
	float dotVH = saturate( dot( geometryViewDir, halfDir ) );
	vec3 F = F_Schlick( material.specularColor, material.specularF90, dotVH );
	#ifdef USE_RETROREFLECTION
		vec3 retroHalfDir = normalize( directLight.direction + retroViewDir );
		float dotRetroVH = saturate( dot( retroViewDir, retroHalfDir ) );
		vec3 retroF = F_Schlick( material.specularColor, material.specularF90, dotRetroVH );
		F = mix( F, retroF, saturate( material.retroreflectivity ) );
	#endif
	reflectedLight.directDiffuse += irradiance * BRDF_Lambert( material.diffuseContribution ) * ( 1.0 - F );
}
void RE_IndirectDiffuse_Physical( const in vec3 irradiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight ) {
	vec3 singleScattering = vec3( 0.0 );
	vec3 multiScattering = vec3( 0.0 );
	#ifdef USE_IRIDESCENCE
		computeMultiscatteringIridescence( material.dfg, material.specularColor, material.specularF90, material.iridescence, material.iridescenceF0Dielectric, singleScattering, multiScattering );
	#else
		computeMultiscattering( material.dfg, material.specularColor, material.specularF90, singleScattering, multiScattering );
	#endif
	vec3 diffuse = irradiance * BRDF_Lambert( material.diffuseContribution ) * ( 1.0 - singleScattering - multiScattering );
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		sheenSpecularIndirect += irradiance * material.sheenColor * sheenAlbedo * RECIPROCAL_PI;
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		diffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectDiffuse += diffuse;
}
void RE_IndirectSpecular_Physical( const in vec3 radiance, const in vec3 irradiance, const in vec3 clearcoatRadiance, const in vec3 geometryPosition, const in vec3 geometryNormal, const in vec3 geometryViewDir, const in vec3 geometryClearcoatNormal, const in PhysicalMaterial material, inout ReflectedLight reflectedLight) {
	#ifdef USE_CLEARCOAT
		clearcoatSpecularIndirect += clearcoatRadiance * EnvironmentBRDF( geometryClearcoatNormal, geometryViewDir, material.clearcoatF0, material.clearcoatF90, material.clearcoatRoughness );
	#endif
	#ifdef USE_SHEEN
		sheenSpecularIndirect += irradiance * material.sheenColor * IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness ) * RECIPROCAL_PI;
 	#endif
	vec3 singleScatteringDielectric = vec3( 0.0 );
	vec3 multiScatteringDielectric = vec3( 0.0 );
	vec3 singleScatteringMetallic = vec3( 0.0 );
	vec3 multiScatteringMetallic = vec3( 0.0 );
	#ifdef USE_IRIDESCENCE
		computeMultiscatteringIridescence( material.dfg, material.specularColor, material.specularF90, material.iridescence, material.iridescenceF0Dielectric, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscatteringIridescence( material.dfg, material.diffuseColor, material.specularF90, material.iridescence, material.iridescenceF0Metallic, singleScatteringMetallic, multiScatteringMetallic );
	#else
		computeMultiscattering( material.dfg, material.specularColor, material.specularF90, singleScatteringDielectric, multiScatteringDielectric );
		computeMultiscattering( material.dfg, material.diffuseColor, material.specularF90, singleScatteringMetallic, multiScatteringMetallic );
	#endif
	vec3 singleScattering = mix( singleScatteringDielectric, singleScatteringMetallic, material.metalness );
	vec3 multiScattering = mix( multiScatteringDielectric, multiScatteringMetallic, material.metalness );
	vec3 totalScatteringDielectric = singleScatteringDielectric + multiScatteringDielectric;
	vec3 diffuse = material.diffuseContribution * ( 1.0 - totalScatteringDielectric );
	vec3 cosineWeightedIrradiance = irradiance * RECIPROCAL_PI;
	vec3 indirectSpecular = radiance * singleScattering;
	indirectSpecular += multiScattering * cosineWeightedIrradiance;
	vec3 indirectDiffuse = diffuse * cosineWeightedIrradiance;
	#ifdef USE_SHEEN
		float sheenAlbedo = IBLSheenBRDF( geometryNormal, geometryViewDir, material.sheenRoughness );
		float sheenEnergyComp = 1.0 - max3( material.sheenColor ) * sheenAlbedo;
		indirectSpecular *= sheenEnergyComp;
		indirectDiffuse *= sheenEnergyComp;
	#endif
	reflectedLight.indirectSpecular += indirectSpecular;
	reflectedLight.indirectDiffuse += indirectDiffuse;
}
#define RE_Direct				RE_Direct_Physical
#define RE_Direct_RectArea		RE_Direct_RectArea_Physical
#define RE_IndirectDiffuse		RE_IndirectDiffuse_Physical
#define RE_IndirectSpecular		RE_IndirectSpecular_Physical
float computeSpecularOcclusion( const in float dotNV, const in float ambientOcclusion, const in float roughness ) {
	return saturate( pow( dotNV + ambientOcclusion, exp2( - 16.0 * roughness - 1.0 ) ) - 1.0 + ambientOcclusion );
}`,Es=`
vec3 geometryPosition = - vViewPosition;
vec3 geometryNormal = normal;
vec3 geometryViewDir = ( isOrthographic ) ? vec3( 0, 0, 1 ) : normalize( vViewPosition );
vec3 geometryClearcoatNormal = vec3( 0.0 );
#ifdef USE_CLEARCOAT
	geometryClearcoatNormal = clearcoatNormal;
#endif
#ifdef USE_IRIDESCENCE
	float dotNVi = saturate( dot( normal, geometryViewDir ) );
	if ( material.iridescenceThickness == 0.0 ) {
		material.iridescence = 0.0;
	} else {
		material.iridescence = saturate( material.iridescence );
	}
	if ( material.iridescence > 0.0 ) {
		vec3 iridescenceFresnelDielectric = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.specularColor );
		vec3 iridescenceFresnelMetallic = evalIridescence( 1.0, material.iridescenceIOR, dotNVi, material.iridescenceThickness, material.diffuseColor );
		material.iridescenceFresnel = mix( iridescenceFresnelDielectric, iridescenceFresnelMetallic, material.metalness );
		material.iridescenceF0Dielectric = Schlick_to_F0( iridescenceFresnelDielectric, 1.0, dotNVi );
		material.iridescenceF0Metallic = Schlick_to_F0( iridescenceFresnelMetallic, 1.0, dotNVi );
	}
#endif
#ifdef STANDARD
	float dotNVms = saturate( dot( geometryNormal, geometryViewDir ) );
	material.dfg = texture2D( dfgLUT, vec2( material.roughness, dotNVms ) ).rg;
	#if ( NUM_SUN_LIGHTS > 0 || NUM_DIR_LIGHTS > 0 || NUM_POINT_LIGHTS > 0 || NUM_SPOT_LIGHTS > 0 )
		float EssMs = material.dfg.x + material.dfg.y;
		material.multiScatteringCompensation = 1.0 + material.specularColorBlended * ( 1.0 / EssMs - 1.0 );
	#endif
#endif
IncidentLight directLight;
#if ( NUM_POINT_LIGHTS > 0 ) && defined( RE_Direct )
	PointLight pointLight;
	#if defined( USE_SHADOWMAP ) && NUM_POINT_LIGHT_SHADOWS > 0
	PointLightShadow pointLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHTS; i ++ ) {
		pointLight = pointLights[ i ];
		getPointLightInfo( pointLight, geometryPosition, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_POINT_LIGHT_SHADOWS ) && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
		pointLightShadow = pointLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getPointShadow( pointShadowMap[ i ], pointLightShadow.shadowMapSize, pointLightShadow.shadowIntensity, pointLightShadow.shadowBias, pointLightShadow.shadowRadius, vPointShadowCoord[ i ], pointLightShadow.shadowCameraNear, pointLightShadow.shadowCameraFar ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_SPOT_LIGHTS > 0 ) && defined( RE_Direct )
	SpotLight spotLight;
	vec4 spotColor;
	vec3 spotLightCoord;
	bool inSpotLightMap;
	#if defined( USE_SHADOWMAP ) && NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHTS; i ++ ) {
		spotLight = spotLights[ i ];
		getSpotLightInfo( spotLight, geometryPosition, directLight );
		#if ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#define SPOT_LIGHT_MAP_INDEX UNROLLED_LOOP_INDEX
		#elif ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		#define SPOT_LIGHT_MAP_INDEX NUM_SPOT_LIGHT_MAPS
		#else
		#define SPOT_LIGHT_MAP_INDEX ( UNROLLED_LOOP_INDEX - NUM_SPOT_LIGHT_SHADOWS + NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS )
		#endif
		#if ( SPOT_LIGHT_MAP_INDEX < NUM_SPOT_LIGHT_MAPS )
			spotLightCoord = vSpotLightCoord[ i ].xyz / vSpotLightCoord[ i ].w;
			inSpotLightMap = all( lessThan( abs( spotLightCoord * 2. - 1. ), vec3( 1.0 ) ) );
			spotColor = texture2D( spotLightMap[ SPOT_LIGHT_MAP_INDEX ], spotLightCoord.xy );
			directLight.color = inSpotLightMap ? directLight.color * spotColor.rgb : directLight.color;
		#endif
		#undef SPOT_LIGHT_MAP_INDEX
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
		spotLightShadow = spotLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( spotShadowMap[ i ], spotLightShadow.shadowMapSize, spotLightShadow.shadowIntensity, spotLightShadow.shadowBias, spotLightShadow.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_SUN_LIGHTS > 0 ) && defined( RE_Direct )
	SunLight sunLight;
	#if defined( USE_SHADOWMAP ) && NUM_SUN_LIGHT_SHADOWS > 0
	SunLightShadow sunLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SUN_LIGHTS; i ++ ) {
		sunLight = sunLights[ i ];
		getSunLightInfo( sunLight, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_SUN_LIGHT_SHADOWS )
		sunLightShadow = sunLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getSunShadow( sunShadowMap[ i ], sunLightShadow, UNROLLED_LOOP_INDEX ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_DIR_LIGHTS > 0 ) && defined( RE_Direct )
	DirectionalLight directionalLight;
	#if defined( USE_SHADOWMAP ) && NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLightShadow;
	#endif
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHTS; i ++ ) {
		directionalLight = directionalLights[ i ];
		getDirectionalLightInfo( directionalLight, directLight );
		#if defined( USE_SHADOWMAP ) && ( UNROLLED_LOOP_INDEX < NUM_DIR_LIGHT_SHADOWS )
		directionalLightShadow = directionalLightShadows[ i ];
		directLight.color *= ( directLight.visible && receiveShadow ) ? getShadow( directionalShadowMap[ i ], directionalLightShadow.shadowMapSize, directionalLightShadow.shadowIntensity, directionalLightShadow.shadowBias, directionalLightShadow.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
		#endif
		RE_Direct( directLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if ( NUM_RECT_AREA_LIGHTS > 0 ) && defined( RE_Direct_RectArea )
	RectAreaLight rectAreaLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_RECT_AREA_LIGHTS; i ++ ) {
		rectAreaLight = rectAreaLights[ i ];
		RE_Direct_RectArea( rectAreaLight, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
	}
	#pragma unroll_loop_end
#endif
#if defined( RE_IndirectDiffuse )
	vec3 iblIrradiance = vec3( 0.0 );
	vec3 irradiance = getAmbientLightIrradiance( ambientLightColor );
	#if defined( USE_LIGHT_PROBES )
		irradiance += getLightProbeIrradiance( lightProbe, geometryNormal );
	#endif
	#if ( NUM_HEMI_LIGHTS > 0 )
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_HEMI_LIGHTS; i ++ ) {
			irradiance += getHemisphereLightIrradiance( hemisphereLights[ i ], geometryNormal );
		}
		#pragma unroll_loop_end
	#endif
	#ifdef USE_LIGHT_PROBES_GRID
		vec3 probeWorldPos = ( ( vec4( geometryPosition, 1.0 ) - viewMatrix[ 3 ] ) * viewMatrix ).xyz;
		vec3 probeWorldNormal = transformNormalByInverseViewMatrix( geometryNormal, viewMatrix );
		irradiance += getLightProbeGridIrradiance( probeWorldPos, probeWorldNormal );
	#endif
#endif
#if defined( RE_IndirectSpecular )
	vec3 radiance = vec3( 0.0 );
	vec3 clearcoatRadiance = vec3( 0.0 );
#endif`,xs=`#if defined( RE_IndirectDiffuse )
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		vec3 lightMapIrradiance = lightMapTexel.rgb * lightMapIntensity;
		irradiance += lightMapIrradiance;
	#endif
	#if defined( USE_ENVMAP ) && defined( ENVMAP_TYPE_CUBE_UV )
		#if defined( STANDARD ) || defined( LAMBERT ) || defined( PHONG )
			iblIrradiance += getIBLIrradiance( geometryNormal );
		#endif
	#endif
#endif
#if defined( USE_ENVMAP ) && defined( RE_IndirectSpecular )
	#ifdef USE_ANISOTROPY
		vec3 iblRadiance = getIBLAnisotropyRadiance( geometryViewDir, geometryNormal, material.roughness, material.anisotropyB, material.anisotropy );
	#else
		vec3 iblRadiance = getIBLRadiance( geometryViewDir, geometryNormal, material.roughness );
	#endif
	#ifdef USE_RETROREFLECTION
		#ifdef USE_ANISOTROPY
			vec3 retroIBLRadiance = getIBLAnisotropyRetroRadiance( geometryViewDir, geometryNormal, material.roughness, material.anisotropyB, material.anisotropy );
		#else
			vec3 retroIBLRadiance = getIBLRetroRadiance( geometryViewDir, geometryNormal, material.roughness );
		#endif
		iblRadiance = mix( iblRadiance, retroIBLRadiance, saturate( material.retroreflectivity ) );
	#endif
	radiance += iblRadiance;
	#ifdef USE_CLEARCOAT
		clearcoatRadiance += getIBLRadiance( geometryViewDir, geometryClearcoatNormal, material.clearcoatRoughness );
	#endif
#endif`,Ms=`#if defined( RE_IndirectDiffuse )
	#if defined( LAMBERT ) || defined( PHONG )
		irradiance += iblIrradiance;
	#endif
	RE_IndirectDiffuse( irradiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif
#if defined( RE_IndirectSpecular )
	RE_IndirectSpecular( radiance, iblIrradiance, clearcoatRadiance, geometryPosition, geometryNormal, geometryViewDir, geometryClearcoatNormal, material, reflectedLight );
#endif`,Ts=`#ifdef USE_LIGHT_PROBES_GRID
uniform highp sampler3D probesSH;
uniform vec3 probesMin;
uniform vec3 probesMax;
uniform vec3 probesResolution;
vec3 getLightProbeGridIrradiance( vec3 worldPos, vec3 worldNormal ) {
	vec3 res = probesResolution;
	vec3 gridRange = probesMax - probesMin;
	vec3 resMinusOne = res - 1.0;
	vec3 probeSpacing = gridRange / resMinusOne;
	vec3 samplePos = worldPos + worldNormal * probeSpacing * 0.5;
	vec3 uvw = clamp( ( samplePos - probesMin ) / gridRange, 0.0, 1.0 );
	uvw = uvw * resMinusOne / res + 0.5 / res;
	float nz          = res.z;
	float paddedSlices = nz + 2.0;
	float atlasDepth  = 7.0 * paddedSlices;
	float uvZBase     = uvw.z * nz + 1.0;
	vec4 s0 = texture( probesSH, vec3( uvw.xy, ( uvZBase                       ) / atlasDepth ) );
	vec4 s1 = texture( probesSH, vec3( uvw.xy, ( uvZBase +       paddedSlices   ) / atlasDepth ) );
	vec4 s2 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 2.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s3 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 3.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s4 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 4.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s5 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 5.0 * paddedSlices   ) / atlasDepth ) );
	vec4 s6 = texture( probesSH, vec3( uvw.xy, ( uvZBase + 6.0 * paddedSlices   ) / atlasDepth ) );
	vec3 c0 = s0.xyz;
	vec3 c1 = vec3( s0.w, s1.xy );
	vec3 c2 = vec3( s1.zw, s2.x );
	vec3 c3 = s2.yzw;
	vec3 c4 = s3.xyz;
	vec3 c5 = vec3( s3.w, s4.xy );
	vec3 c6 = vec3( s4.zw, s5.x );
	vec3 c7 = s5.yzw;
	vec3 c8 = s6.xyz;
	float x = worldNormal.x, y = worldNormal.y, z = worldNormal.z;
	vec3 result = c0 * 0.886227;
	result += c1 * 2.0 * 0.511664 * y;
	result += c2 * 2.0 * 0.511664 * z;
	result += c3 * 2.0 * 0.511664 * x;
	result += c4 * 2.0 * 0.429043 * x * y;
	result += c5 * 2.0 * 0.429043 * y * z;
	result += c6 * ( 0.743125 * z * z - 0.247708 );
	result += c7 * 2.0 * 0.429043 * x * z;
	result += c8 * 0.429043 * ( x * x - y * y );
	return max( result, vec3( 0.0 ) );
}
#endif`,As=`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	gl_FragDepth = vIsPerspective == 0.0 ? gl_FragCoord.z : log2( vFragDepth ) * logDepthBufFC * 0.5;
#endif`,Rs=`#if defined( USE_LOGARITHMIC_DEPTH_BUFFER )
	uniform float logDepthBufFC;
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,bs=`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	varying float vFragDepth;
	varying float vIsPerspective;
#endif`,Cs=`#ifdef USE_LOGARITHMIC_DEPTH_BUFFER
	vFragDepth = 1.0 + gl_Position.w;
	vIsPerspective = float( isPerspectiveMatrix( projectionMatrix ) );
#endif`,Ps=`#ifdef USE_MAP
	vec4 sampledDiffuseColor = texture2D( map, vMapUv );
	#ifdef DECODE_VIDEO_TEXTURE
		sampledDiffuseColor = sRGBTransferEOTF( sampledDiffuseColor );
	#endif
	diffuseColor *= sampledDiffuseColor;
#endif`,Ls=`#ifdef USE_MAP
	uniform sampler2D map;
#endif`,Us=`#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
	#if defined( USE_POINTS_UV )
		vec2 uv = vUv;
	#else
		vec2 uv = ( uvTransform * vec3( gl_PointCoord.x, 1.0 - gl_PointCoord.y, 1 ) ).xy;
	#endif
#endif
#ifdef USE_MAP
	diffuseColor *= texture2D( map, uv );
#endif
#ifdef USE_ALPHAMAP
	diffuseColor.a *= texture2D( alphaMap, uv ).g;
#endif`,ws=`#if defined( USE_POINTS_UV )
	varying vec2 vUv;
#else
	#if defined( USE_MAP ) || defined( USE_ALPHAMAP )
		uniform mat3 uvTransform;
	#endif
#endif
#ifdef USE_MAP
	uniform sampler2D map;
#endif
#ifdef USE_ALPHAMAP
	uniform sampler2D alphaMap;
#endif`,Ds=`float metalnessFactor = metalness;
#ifdef USE_METALNESSMAP
	vec4 texelMetalness = texture2D( metalnessMap, vMetalnessMapUv );
	metalnessFactor *= texelMetalness.b;
#endif`,Is=`#ifdef USE_METALNESSMAP
	uniform sampler2D metalnessMap;
#endif`,Ns=`#ifdef USE_INSTANCING_MORPH
	float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	float morphTargetBaseInfluence = texelFetch( morphTexture, ivec2( 0, gl_InstanceID ), 0 ).r;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		morphTargetInfluences[i] =  texelFetch( morphTexture, ivec2( i + 1, gl_InstanceID ), 0 ).r;
	}
#endif`,ys=`#if defined( USE_MORPHCOLORS )
	vColor *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		#if defined( USE_COLOR_ALPHA )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ) * morphTargetInfluences[ i ];
		#elif defined( USE_COLOR )
			if ( morphTargetInfluences[ i ] != 0.0 ) vColor += getMorph( gl_VertexID, i, 2 ).rgb * morphTargetInfluences[ i ];
		#endif
	}
#endif`,Fs=`#ifdef USE_MORPHNORMALS
	objectNormal *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) objectNormal += getMorph( gl_VertexID, i, 1 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,Os=`#ifdef USE_MORPHTARGETS
	#ifndef USE_INSTANCING_MORPH
		uniform float morphTargetBaseInfluence;
		uniform float morphTargetInfluences[ MORPHTARGETS_COUNT ];
	#endif
	uniform sampler2DArray morphTargetsTexture;
	uniform ivec2 morphTargetsTextureSize;
	vec4 getMorph( const in int vertexIndex, const in int morphTargetIndex, const in int offset ) {
		int texelIndex = vertexIndex * MORPHTARGETS_TEXTURE_STRIDE + offset;
		int y = texelIndex / morphTargetsTextureSize.x;
		int x = texelIndex - y * morphTargetsTextureSize.x;
		ivec3 morphUV = ivec3( x, y, morphTargetIndex );
		return texelFetch( morphTargetsTexture, morphUV, 0 );
	}
#endif`,Bs=`#ifdef USE_MORPHTARGETS
	transformed *= morphTargetBaseInfluence;
	for ( int i = 0; i < MORPHTARGETS_COUNT; i ++ ) {
		if ( morphTargetInfluences[ i ] != 0.0 ) transformed += getMorph( gl_VertexID, i, 0 ).xyz * morphTargetInfluences[ i ];
	}
#endif`,Gs=`float faceDirection = gl_FrontFacing ? 1.0 : - 1.0;
#ifdef FLAT_SHADED
	vec3 fdx = dFdx( vViewPosition );
	vec3 fdy = dFdy( vViewPosition );
	vec3 normal = normalize( cross( fdx, fdy ) );
#else
	vec3 normal = normalize( vNormal );
	#ifdef DOUBLE_SIDED
		normal *= faceDirection;
	#endif
#endif
#if defined( USE_NORMALMAP_TANGENTSPACE ) || defined( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY )
	#ifdef USE_TANGENT
		mat3 tbn = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn = getTangentFrame( - vViewPosition, normal,
		#if defined( USE_NORMALMAP )
			vNormalMapUv
		#elif defined( USE_CLEARCOAT_NORMALMAP )
			vClearcoatNormalMapUv
		#else
			vUv
		#endif
		);
	#endif
	#ifdef DOUBLE_SIDED
		tbn[0] *= faceDirection;
		tbn[1] *= faceDirection;
	#endif
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	#ifdef USE_TANGENT
		mat3 tbn2 = mat3( normalize( vTangent ), normalize( vBitangent ), normal );
	#else
		mat3 tbn2 = getTangentFrame( - vViewPosition, normal, vClearcoatNormalMapUv );
	#endif
	#ifdef DOUBLE_SIDED
		tbn2[0] *= faceDirection;
		tbn2[1] *= faceDirection;
	#endif
#endif
vec3 nonPerturbedNormal = normal;`,Hs=`#ifdef USE_NORMALMAP_OBJECTSPACE
	normal = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	#ifdef FLIP_SIDED
		normal = - normal;
	#endif
	#ifdef DOUBLE_SIDED
		normal = normal * faceDirection;
	#endif
	normal = normalize( normalMatrix * normal );
#elif defined( USE_NORMALMAP_TANGENTSPACE )
	vec3 mapN = texture2D( normalMap, vNormalMapUv ).xyz * 2.0 - 1.0;
	#if defined( USE_PACKED_NORMALMAP )
		mapN = vec3( mapN.xy, sqrt( saturate( 1.0 - dot( mapN.xy, mapN.xy ) ) ) );
	#endif
	mapN.xy *= normalScale;
	normal = normalize( tbn * mapN );
#elif defined( USE_BUMPMAP )
	normal = perturbNormalArb( - vViewPosition, normal, dHdxy_fwd(), faceDirection );
#endif`,Vs=`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,Ws=`#ifndef FLAT_SHADED
	varying vec3 vNormal;
	#ifdef USE_TANGENT
		varying vec3 vTangent;
		varying vec3 vBitangent;
	#endif
#endif`,ks=`#ifndef FLAT_SHADED
	vNormal = normalize( transformedNormal );
	#ifdef USE_TANGENT
		vTangent = normalize( transformedTangent );
		vBitangent = normalize( cross( vNormal, vTangent ) * tangent.w );
		#ifdef FLIP_SIDED
			vBitangent = - vBitangent;
		#endif
	#endif
#endif`,zs=`#ifdef USE_NORMALMAP
	uniform sampler2D normalMap;
	uniform vec2 normalScale;
#endif
#ifdef USE_NORMALMAP_OBJECTSPACE
	uniform mat3 normalMatrix;
#endif
#if ! defined ( USE_TANGENT ) && ( defined ( USE_NORMALMAP_TANGENTSPACE ) || defined ( USE_CLEARCOAT_NORMALMAP ) || defined( USE_ANISOTROPY ) )
	mat3 getTangentFrame( vec3 eye_pos, vec3 surf_norm, vec2 uv ) {
		vec3 q0 = dFdx( eye_pos.xyz );
		vec3 q1 = dFdy( eye_pos.xyz );
		vec2 st0 = dFdx( uv.st );
		vec2 st1 = dFdy( uv.st );
		vec3 N = surf_norm;
		vec3 q1perp = cross( q1, N );
		vec3 q0perp = cross( N, q0 );
		vec3 T = q1perp * st0.x + q0perp * st1.x;
		vec3 B = q1perp * st0.y + q0perp * st1.y;
		float det = max( dot( T, T ), dot( B, B ) );
		float scale = ( det == 0.0 ) ? 0.0 : inversesqrt( det );
		return mat3( T * scale, B * scale, N );
	}
#endif`,Xs=`#ifdef USE_CLEARCOAT
	vec3 clearcoatNormal = nonPerturbedNormal;
#endif`,Ys=`#ifdef USE_CLEARCOAT_NORMALMAP
	vec3 clearcoatMapN = texture2D( clearcoatNormalMap, vClearcoatNormalMapUv ).xyz * 2.0 - 1.0;
	clearcoatMapN.xy *= clearcoatNormalScale;
	clearcoatNormal = normalize( tbn2 * clearcoatMapN );
#endif`,Ks=`#ifdef USE_CLEARCOATMAP
	uniform sampler2D clearcoatMap;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform sampler2D clearcoatNormalMap;
	uniform vec2 clearcoatNormalScale;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform sampler2D clearcoatRoughnessMap;
#endif`,qs=`#ifdef USE_IRIDESCENCEMAP
	uniform sampler2D iridescenceMap;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform sampler2D iridescenceThicknessMap;
#endif`,Zs=`#ifdef OPAQUE
diffuseColor.a = 1.0;
#endif
#ifdef USE_TRANSMISSION
diffuseColor.a *= material.transmissionAlpha;
#endif
gl_FragColor = vec4( outgoingLight, diffuseColor.a );`,$s=`vec3 packNormalToRGB( const in vec3 normal ) {
	return normalize( normal ) * 0.5 + 0.5;
}
vec3 unpackRGBToNormal( const in vec3 rgb ) {
	return 2.0 * rgb.xyz - 1.0;
}
const float PackUpscale = 256. / 255.;const float UnpackDownscale = 255. / 256.;const float ShiftRight8 = 1. / 256.;
const float Inv255 = 1. / 255.;
const vec4 PackFactors = vec4( 1.0, 256.0, 256.0 * 256.0, 256.0 * 256.0 * 256.0 );
const vec2 UnpackFactors2 = vec2( UnpackDownscale, 1.0 / PackFactors.g );
const vec3 UnpackFactors3 = vec3( UnpackDownscale / PackFactors.rg, 1.0 / PackFactors.b );
const vec4 UnpackFactors4 = vec4( UnpackDownscale / PackFactors.rgb, 1.0 / PackFactors.a );
vec4 packDepthToRGBA( const in float v ) {
	if( v <= 0.0 )
		return vec4( 0., 0., 0., 0. );
	if( v >= 1.0 )
		return vec4( 1., 1., 1., 1. );
	float vuf;
	float af = modf( v * PackFactors.a, vuf );
	float bf = modf( vuf * ShiftRight8, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec4( vuf * Inv255, gf * PackUpscale, bf * PackUpscale, af );
}
vec3 packDepthToRGB( const in float v ) {
	if( v <= 0.0 )
		return vec3( 0., 0., 0. );
	if( v >= 1.0 )
		return vec3( 1., 1., 1. );
	float vuf;
	float bf = modf( v * PackFactors.b, vuf );
	float gf = modf( vuf * ShiftRight8, vuf );
	return vec3( vuf * Inv255, gf * PackUpscale, bf );
}
vec2 packDepthToRG( const in float v ) {
	if( v <= 0.0 )
		return vec2( 0., 0. );
	if( v >= 1.0 )
		return vec2( 1., 1. );
	float vuf;
	float gf = modf( v * 256., vuf );
	return vec2( vuf * Inv255, gf );
}
float unpackRGBAToDepth( const in vec4 v ) {
	return dot( v, UnpackFactors4 );
}
float unpackRGBToDepth( const in vec3 v ) {
	return dot( v, UnpackFactors3 );
}
float unpackRGToDepth( const in vec2 v ) {
	return v.r * UnpackFactors2.r + v.g * UnpackFactors2.g;
}
vec4 pack2HalfToRGBA( const in vec2 v ) {
	vec4 r = vec4( v.x, fract( v.x * 255.0 ), v.y, fract( v.y * 255.0 ) );
	return vec4( r.x - r.y / 255.0, r.y, r.z - r.w / 255.0, r.w );
}
vec2 unpackRGBATo2Half( const in vec4 v ) {
	return vec2( v.x + ( v.y / 255.0 ), v.z + ( v.w / 255.0 ) );
}
float viewZToOrthographicDepth( const in float viewZ, const in float near, const in float far ) {
	return ( viewZ + near ) / ( near - far );
}
float orthographicDepthToViewZ( const in float depth, const in float near, const in float far ) {
	#ifdef USE_REVERSED_DEPTH_BUFFER
	
		return depth * ( far - near ) - far;
	#else
		return depth * ( near - far ) - near;
	#endif
}
float viewZToPerspectiveDepth( const in float viewZ, const in float near, const in float far ) {
	return ( ( near + viewZ ) * far ) / ( ( far - near ) * viewZ );
}
float perspectiveDepthToViewZ( const in float depth, const in float near, const in float far ) {
	
	#ifdef USE_REVERSED_DEPTH_BUFFER
		return ( near * far ) / ( ( near - far ) * depth - near );
	#else
		return ( near * far ) / ( ( far - near ) * depth - far );
	#endif
}`,Qs=`#ifdef PREMULTIPLIED_ALPHA
	gl_FragColor.rgb *= gl_FragColor.a;
#endif`,Js=`vec4 mvPosition = vec4( transformed, 1.0 );
#ifdef USE_BATCHING
	mvPosition = batchingMatrix * mvPosition;
#endif
#ifdef USE_INSTANCING
	mvPosition = instanceMatrix * mvPosition;
#endif
mvPosition = modelViewMatrix * mvPosition;
gl_Position = projectionMatrix * mvPosition;`,js=`#ifdef DITHERING
	gl_FragColor.rgb = dithering( gl_FragColor.rgb );
#endif`,el=`#ifdef DITHERING
	vec3 dithering( vec3 color ) {
		float grid_position = rand( gl_FragCoord.xy );
		vec3 dither_shift_RGB = vec3( 0.25 / 255.0, -0.25 / 255.0, 0.25 / 255.0 );
		dither_shift_RGB = mix( 2.0 * dither_shift_RGB, -2.0 * dither_shift_RGB, grid_position );
		return color + dither_shift_RGB;
	}
#endif`,tl=`float roughnessFactor = roughness;
#ifdef USE_ROUGHNESSMAP
	vec4 texelRoughness = texture2D( roughnessMap, vRoughnessMapUv );
	roughnessFactor *= texelRoughness.g;
#endif`,nl=`#ifdef USE_ROUGHNESSMAP
	uniform sampler2D roughnessMap;
#endif`,il=`#if NUM_SPOT_LIGHT_COORDS > 0
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#if NUM_SPOT_LIGHT_MAPS > 0
	uniform sampler2D spotLightMap[ NUM_SPOT_LIGHT_MAPS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_SUN_LIGHT_SHADOWS > 0
		#define SUN_LIGHT_CASCADES 2
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow sunShadowMap[ NUM_SUN_LIGHT_SHADOWS ];
		#else
			uniform sampler2D sunShadowMap[ NUM_SUN_LIGHT_SHADOWS ];
		#endif
		uniform mat4 sunShadowMatrix[ NUM_SUN_LIGHT_SHADOWS * SUN_LIGHT_CASCADES ];
		uniform vec4 sunShadowCascade[ NUM_SUN_LIGHT_SHADOWS * SUN_LIGHT_CASCADES ];
		varying vec4 vSunShadowWorldPosition;
		varying vec3 vSunShadowWorldNormal;
		struct SunLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SunLightShadow sunLightShadows[ NUM_SUN_LIGHT_SHADOWS ];
	#endif
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#else
			uniform sampler2D directionalShadowMap[ NUM_DIR_LIGHT_SHADOWS ];
		#endif
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform sampler2DShadow spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#else
			uniform sampler2D spotShadowMap[ NUM_SPOT_LIGHT_SHADOWS ];
		#endif
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#if defined( SHADOWMAP_TYPE_PCF )
			uniform samplerCubeShadow pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#elif defined( SHADOWMAP_TYPE_BASIC )
			uniform samplerCube pointShadowMap[ NUM_POINT_LIGHT_SHADOWS ];
		#endif
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float interleavedGradientNoise( vec2 position ) {
			return fract( 52.9829189 * fract( dot( position, vec2( 0.06711056, 0.00583715 ) ) ) );
		}
		vec2 vogelDiskSample( int sampleIndex, int samplesCount, float phi ) {
			const float goldenAngle = 2.399963229728653;
			float r = sqrt( ( float( sampleIndex ) + 0.5 ) / float( samplesCount ) );
			float theta = float( sampleIndex ) * goldenAngle + phi;
			return vec2( cos( theta ), sin( theta ) ) * r;
		}
	#endif
	#if defined( SHADOWMAP_TYPE_PCF )
		float getShadow( sampler2DShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			shadowCoord.z += shadowBias;
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 texelSize = vec2( 1.0 ) / shadowMapSize;
				float radius = shadowRadius * texelSize.x;
				float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
				shadow = (
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 0, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 1, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 2, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 3, 5, phi ) * radius, shadowCoord.z ) ) +
					texture( shadowMap, vec3( shadowCoord.xy + vogelDiskSample( 4, 5, phi ) * radius, shadowCoord.z ) )
				) * 0.2;
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#elif defined( SHADOWMAP_TYPE_VSM )
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				vec2 distribution = texture2D( shadowMap, shadowCoord.xy ).rg;
				float mean = distribution.x;
				float variance = distribution.y * distribution.y;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					float hard_shadow = step( mean, shadowCoord.z );
				#else
					float hard_shadow = step( shadowCoord.z, mean );
				#endif
				
				if ( hard_shadow == 1.0 ) {
					shadow = 1.0;
				} else {
					variance = max( variance, 0.0000001 );
					float d = shadowCoord.z - mean;
					float p_max = variance / ( variance + d * d );
					p_max = clamp( ( p_max - 0.3 ) / 0.65, 0.0, 1.0 );
					shadow = max( hard_shadow, p_max );
				}
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#else
		float getShadow( sampler2D shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord ) {
			float shadow = 1.0;
			shadowCoord.xyz /= shadowCoord.w;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				shadowCoord.z -= shadowBias;
			#else
				shadowCoord.z += shadowBias;
			#endif
			bool inFrustum = shadowCoord.x >= 0.0 && shadowCoord.x <= 1.0 && shadowCoord.y >= 0.0 && shadowCoord.y <= 1.0;
			bool frustumTest = inFrustum && shadowCoord.z <= 1.0;
			if ( frustumTest ) {
				float depth = texture2D( shadowMap, shadowCoord.xy ).r;
				#ifdef USE_REVERSED_DEPTH_BUFFER
					shadow = step( depth, shadowCoord.z );
				#else
					shadow = step( shadowCoord.z, depth );
				#endif
			}
			return mix( 1.0, shadow, shadowIntensity );
		}
	#endif
	#if NUM_SUN_LIGHT_SHADOWS > 0
		float getSunShadow(
			#if defined( SHADOWMAP_TYPE_PCF )
				sampler2DShadow shadowMap,
			#else
				sampler2D shadowMap,
			#endif
			SunLightShadow sunLightShadow,
			int shadowIndex
		) {
			vec4 shadowWorldPosition = vec4( vSunShadowWorldPosition.xyz + vSunShadowWorldNormal * sunLightShadow.shadowNormalBias, 1.0 );
			float viewDepth = vSunShadowWorldPosition.w;
			int cascadeOffset = shadowIndex * SUN_LIGHT_CASCADES;
			float shadow = 1.0;
			for ( int i = SUN_LIGHT_CASCADES - 1; i >= 0; i -- ) {
				vec4 cascade = sunShadowCascade[ cascadeOffset + i ];
				if ( viewDepth >= cascade.x && viewDepth < cascade.y ) {
					float cascadeShadow = getShadow(
						shadowMap,
						sunLightShadow.shadowMapSize,
						sunLightShadow.shadowIntensity,
						sunLightShadow.shadowBias,
						sunLightShadow.shadowRadius,
						sunShadowMatrix[ cascadeOffset + i ] * shadowWorldPosition
					);
					shadow = mix( cascadeShadow, shadow, smoothstep( cascade.z, cascade.y, viewDepth ) );
				}
			}
			return shadow;
		}
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
	#if defined( SHADOWMAP_TYPE_PCF )
	float getPointShadow( samplerCubeShadow shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 bd3D = normalize( lightToPosition );
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			#ifdef USE_REVERSED_DEPTH_BUFFER
				float dp = ( shadowCameraNear * ( shadowCameraFar - viewSpaceZ ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp -= shadowBias;
			#else
				float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
				dp += shadowBias;
			#endif
			float texelSize = shadowRadius / shadowMapSize.x;
			vec3 absDir = abs( bd3D );
			vec3 tangent = absDir.x > absDir.z ? vec3( 0.0, 1.0, 0.0 ) : vec3( 1.0, 0.0, 0.0 );
			tangent = normalize( cross( bd3D, tangent ) );
			vec3 bitangent = cross( bd3D, tangent );
			float phi = interleavedGradientNoise( gl_FragCoord.xy ) * PI2;
			vec2 sample0 = vogelDiskSample( 0, 5, phi );
			vec2 sample1 = vogelDiskSample( 1, 5, phi );
			vec2 sample2 = vogelDiskSample( 2, 5, phi );
			vec2 sample3 = vogelDiskSample( 3, 5, phi );
			vec2 sample4 = vogelDiskSample( 4, 5, phi );
			shadow = (
				texture( shadowMap, vec4( bd3D + ( tangent * sample0.x + bitangent * sample0.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample1.x + bitangent * sample1.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample2.x + bitangent * sample2.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample3.x + bitangent * sample3.y ) * texelSize, dp ) ) +
				texture( shadowMap, vec4( bd3D + ( tangent * sample4.x + bitangent * sample4.y ) * texelSize, dp ) )
			) * 0.2;
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#elif defined( SHADOWMAP_TYPE_BASIC )
	float getPointShadow( samplerCube shadowMap, vec2 shadowMapSize, float shadowIntensity, float shadowBias, float shadowRadius, vec4 shadowCoord, float shadowCameraNear, float shadowCameraFar ) {
		float shadow = 1.0;
		vec3 lightToPosition = shadowCoord.xyz;
		vec3 absVec = abs( lightToPosition );
		float viewSpaceZ = max( max( absVec.x, absVec.y ), absVec.z );
		if ( viewSpaceZ - shadowCameraFar <= 0.0 && viewSpaceZ - shadowCameraNear >= 0.0 ) {
			float dp = ( shadowCameraFar * ( viewSpaceZ - shadowCameraNear ) ) / ( viewSpaceZ * ( shadowCameraFar - shadowCameraNear ) );
			dp += shadowBias;
			vec3 bd3D = normalize( lightToPosition );
			float depth = textureCube( shadowMap, bd3D ).r;
			#ifdef USE_REVERSED_DEPTH_BUFFER
				depth = 1.0 - depth;
			#endif
			shadow = step( dp, depth );
		}
		return mix( 1.0, shadow, shadowIntensity );
	}
	#endif
	#endif
#endif`,rl=`#if NUM_SPOT_LIGHT_COORDS > 0
	uniform mat4 spotLightMatrix[ NUM_SPOT_LIGHT_COORDS ];
	varying vec4 vSpotLightCoord[ NUM_SPOT_LIGHT_COORDS ];
#endif
#ifdef USE_SHADOWMAP
	#if NUM_SUN_LIGHT_SHADOWS > 0
		varying vec4 vSunShadowWorldPosition;
		varying vec3 vSunShadowWorldNormal;
	#endif
	#if NUM_DIR_LIGHT_SHADOWS > 0
		uniform mat4 directionalShadowMatrix[ NUM_DIR_LIGHT_SHADOWS ];
		varying vec4 vDirectionalShadowCoord[ NUM_DIR_LIGHT_SHADOWS ];
		struct DirectionalLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform DirectionalLightShadow directionalLightShadows[ NUM_DIR_LIGHT_SHADOWS ];
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
		struct SpotLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
		};
		uniform SpotLightShadow spotLightShadows[ NUM_SPOT_LIGHT_SHADOWS ];
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		uniform mat4 pointShadowMatrix[ NUM_POINT_LIGHT_SHADOWS ];
		varying vec4 vPointShadowCoord[ NUM_POINT_LIGHT_SHADOWS ];
		struct PointLightShadow {
			float shadowIntensity;
			float shadowBias;
			float shadowNormalBias;
			float shadowRadius;
			vec2 shadowMapSize;
			float shadowCameraNear;
			float shadowCameraFar;
		};
		uniform PointLightShadow pointLightShadows[ NUM_POINT_LIGHT_SHADOWS ];
	#endif
#endif`,al=`#if ( defined( USE_SHADOWMAP ) && ( NUM_DIR_LIGHT_SHADOWS > 0 || NUM_SUN_LIGHT_SHADOWS > 0 || NUM_POINT_LIGHT_SHADOWS > 0 ) ) || ( NUM_SPOT_LIGHT_COORDS > 0 )
	#ifdef HAS_NORMAL
		vec3 shadowWorldNormal = transformNormalByInverseViewMatrix( transformedNormal, viewMatrix );
	#else
		vec3 shadowWorldNormal = vec3( 0.0 );
	#endif
	vec4 shadowWorldPosition;
#endif
#if defined( USE_SHADOWMAP )
	#if NUM_SUN_LIGHT_SHADOWS > 0
		vSunShadowWorldPosition = vec4( worldPosition.xyz, - mvPosition.z );
		vSunShadowWorldNormal = shadowWorldNormal;
	#endif
	#if NUM_DIR_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * directionalLightShadows[ i ].shadowNormalBias, 0 );
			vDirectionalShadowCoord[ i ] = directionalShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0
		#pragma unroll_loop_start
		for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
			shadowWorldPosition = worldPosition + vec4( shadowWorldNormal * pointLightShadows[ i ].shadowNormalBias, 0 );
			vPointShadowCoord[ i ] = pointShadowMatrix[ i ] * shadowWorldPosition;
		}
		#pragma unroll_loop_end
	#endif
#endif
#if NUM_SPOT_LIGHT_COORDS > 0
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_COORDS; i ++ ) {
		shadowWorldPosition = worldPosition;
		#if ( defined( USE_SHADOWMAP ) && UNROLLED_LOOP_INDEX < NUM_SPOT_LIGHT_SHADOWS )
			shadowWorldPosition.xyz += shadowWorldNormal * spotLightShadows[ i ].shadowNormalBias;
		#endif
		vSpotLightCoord[ i ] = spotLightMatrix[ i ] * shadowWorldPosition;
	}
	#pragma unroll_loop_end
#endif`,ol=`float getShadowMask() {
	float shadow = 1.0;
	#ifdef USE_SHADOWMAP
	#if NUM_SUN_LIGHT_SHADOWS > 0
	SunLightShadow sunLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SUN_LIGHT_SHADOWS; i ++ ) {
		sunLight = sunLightShadows[ i ];
		shadow *= receiveShadow ? getSunShadow( sunShadowMap[ i ], sunLight, UNROLLED_LOOP_INDEX ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_DIR_LIGHT_SHADOWS > 0
	DirectionalLightShadow directionalLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_DIR_LIGHT_SHADOWS; i ++ ) {
		directionalLight = directionalLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( directionalShadowMap[ i ], directionalLight.shadowMapSize, directionalLight.shadowIntensity, directionalLight.shadowBias, directionalLight.shadowRadius, vDirectionalShadowCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_SPOT_LIGHT_SHADOWS > 0
	SpotLightShadow spotLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_SPOT_LIGHT_SHADOWS; i ++ ) {
		spotLight = spotLightShadows[ i ];
		shadow *= receiveShadow ? getShadow( spotShadowMap[ i ], spotLight.shadowMapSize, spotLight.shadowIntensity, spotLight.shadowBias, spotLight.shadowRadius, vSpotLightCoord[ i ] ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#if NUM_POINT_LIGHT_SHADOWS > 0 && ( defined( SHADOWMAP_TYPE_PCF ) || defined( SHADOWMAP_TYPE_BASIC ) )
	PointLightShadow pointLight;
	#pragma unroll_loop_start
	for ( int i = 0; i < NUM_POINT_LIGHT_SHADOWS; i ++ ) {
		pointLight = pointLightShadows[ i ];
		shadow *= receiveShadow ? getPointShadow( pointShadowMap[ i ], pointLight.shadowMapSize, pointLight.shadowIntensity, pointLight.shadowBias, pointLight.shadowRadius, vPointShadowCoord[ i ], pointLight.shadowCameraNear, pointLight.shadowCameraFar ) : 1.0;
	}
	#pragma unroll_loop_end
	#endif
	#endif
	return shadow;
}`,sl=`#ifdef USE_SKINNING
	mat4 boneMatX = getBoneMatrix( skinIndex.x );
	mat4 boneMatY = getBoneMatrix( skinIndex.y );
	mat4 boneMatZ = getBoneMatrix( skinIndex.z );
	mat4 boneMatW = getBoneMatrix( skinIndex.w );
#endif`,ll=`#ifdef USE_SKINNING
	uniform mat4 bindMatrix;
	uniform mat4 bindMatrixInverse;
	uniform highp sampler2D boneTexture;
	mat4 getBoneMatrix( const in float i ) {
		int size = textureSize( boneTexture, 0 ).x;
		int j = int( i ) * 4;
		int x = j % size;
		int y = j / size;
		vec4 v1 = texelFetch( boneTexture, ivec2( x, y ), 0 );
		vec4 v2 = texelFetch( boneTexture, ivec2( x + 1, y ), 0 );
		vec4 v3 = texelFetch( boneTexture, ivec2( x + 2, y ), 0 );
		vec4 v4 = texelFetch( boneTexture, ivec2( x + 3, y ), 0 );
		return mat4( v1, v2, v3, v4 );
	}
#endif`,cl=`#ifdef USE_SKINNING
	vec4 skinVertex = bindMatrix * vec4( transformed, 1.0 );
	vec4 skinned = vec4( 0.0 );
	skinned += boneMatX * skinVertex * skinWeight.x;
	skinned += boneMatY * skinVertex * skinWeight.y;
	skinned += boneMatZ * skinVertex * skinWeight.z;
	skinned += boneMatW * skinVertex * skinWeight.w;
	transformed = ( bindMatrixInverse * skinned ).xyz;
#endif`,fl=`#ifdef USE_SKINNING
	mat4 skinMatrix = mat4( 0.0 );
	skinMatrix += skinWeight.x * boneMatX;
	skinMatrix += skinWeight.y * boneMatY;
	skinMatrix += skinWeight.z * boneMatZ;
	skinMatrix += skinWeight.w * boneMatW;
	skinMatrix = bindMatrixInverse * skinMatrix * bindMatrix;
	objectNormal = vec4( skinMatrix * vec4( objectNormal, 0.0 ) ).xyz;
	#ifdef USE_TANGENT
		objectTangent = vec4( skinMatrix * vec4( objectTangent, 0.0 ) ).xyz;
	#endif
#endif`,dl=`float specularStrength;
#ifdef USE_SPECULARMAP
	vec4 texelSpecular = texture2D( specularMap, vSpecularMapUv );
	specularStrength = texelSpecular.r;
#else
	specularStrength = 1.0;
#endif`,ul=`#ifdef USE_SPECULARMAP
	uniform sampler2D specularMap;
#endif`,pl=`#if defined( TONE_MAPPING )
	gl_FragColor.rgb = toneMapping( gl_FragColor.rgb );
#endif`,hl=`#ifndef saturate
#define saturate( a ) clamp( a, 0.0, 1.0 )
#endif
uniform float toneMappingExposure;
vec3 LinearToneMapping( vec3 color ) {
	return saturate( toneMappingExposure * color );
}
vec3 ReinhardToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	return saturate( color / ( vec3( 1.0 ) + color ) );
}
vec3 CineonToneMapping( vec3 color ) {
	color *= toneMappingExposure;
	color = max( vec3( 0.0 ), color - 0.004 );
	return pow( ( color * ( 6.2 * color + 0.5 ) ) / ( color * ( 6.2 * color + 1.7 ) + 0.06 ), vec3( 2.2 ) );
}
vec3 RRTAndODTFit( vec3 v ) {
	vec3 a = v * ( v + 0.0245786 ) - 0.000090537;
	vec3 b = v * ( 0.983729 * v + 0.4329510 ) + 0.238081;
	return a / b;
}
vec3 ACESFilmicToneMapping( vec3 color ) {
	const mat3 ACESInputMat = mat3(
		vec3( 0.59719, 0.07600, 0.02840 ),		vec3( 0.35458, 0.90834, 0.13383 ),
		vec3( 0.04823, 0.01566, 0.83777 )
	);
	const mat3 ACESOutputMat = mat3(
		vec3(  1.60475, -0.10208, -0.00327 ),		vec3( -0.53108,  1.10813, -0.07276 ),
		vec3( -0.07367, -0.00605,  1.07602 )
	);
	color *= toneMappingExposure / 0.6;
	color = ACESInputMat * color;
	color = RRTAndODTFit( color );
	color = ACESOutputMat * color;
	return saturate( color );
}
const mat3 LINEAR_REC2020_TO_LINEAR_SRGB = mat3(
	vec3( 1.6605, - 0.1246, - 0.0182 ),
	vec3( - 0.5876, 1.1329, - 0.1006 ),
	vec3( - 0.0728, - 0.0083, 1.1187 )
);
const mat3 LINEAR_SRGB_TO_LINEAR_REC2020 = mat3(
	vec3( 0.6274, 0.0691, 0.0164 ),
	vec3( 0.3293, 0.9195, 0.0880 ),
	vec3( 0.0433, 0.0113, 0.8956 )
);
vec3 agxDefaultContrastApprox( vec3 x ) {
	vec3 x2 = x * x;
	vec3 x4 = x2 * x2;
	return + 15.5 * x4 * x2
		- 40.14 * x4 * x
		+ 31.96 * x4
		- 6.868 * x2 * x
		+ 0.4298 * x2
		+ 0.1191 * x
		- 0.00232;
}
vec3 AgXToneMapping( vec3 color ) {
	const mat3 AgXInsetMatrix = mat3(
		vec3( 0.856627153315983, 0.137318972929847, 0.11189821299995 ),
		vec3( 0.0951212405381588, 0.761241990602591, 0.0767994186031903 ),
		vec3( 0.0482516061458583, 0.101439036467562, 0.811302368396859 )
	);
	const mat3 AgXOutsetMatrix = mat3(
		vec3( 1.1271005818144368, - 0.1413297634984383, - 0.14132976349843826 ),
		vec3( - 0.11060664309660323, 1.157823702216272, - 0.11060664309660294 ),
		vec3( - 0.016493938717834573, - 0.016493938717834257, 1.2519364065950405 )
	);
	const float AgxMinEv = - 12.47393;	const float AgxMaxEv = 4.026069;
	color *= toneMappingExposure;
	color = LINEAR_SRGB_TO_LINEAR_REC2020 * color;
	color = AgXInsetMatrix * color;
	color = max( color, 1e-10 );	color = log2( color );
	color = ( color - AgxMinEv ) / ( AgxMaxEv - AgxMinEv );
	color = clamp( color, 0.0, 1.0 );
	color = agxDefaultContrastApprox( color );
	color = AgXOutsetMatrix * color;
	color = pow( max( vec3( 0.0 ), color ), vec3( 2.2 ) );
	color = LINEAR_REC2020_TO_LINEAR_SRGB * color;
	color = clamp( color, 0.0, 1.0 );
	return color;
}
vec3 NeutralToneMapping( vec3 color ) {
	const float StartCompression = 0.8 - 0.04;
	const float Desaturation = 0.15;
	color *= toneMappingExposure;
	float x = min( color.r, min( color.g, color.b ) );
	float offset = x < 0.08 ? x - 6.25 * x * x : 0.04;
	color -= offset;
	float peak = max( color.r, max( color.g, color.b ) );
	if ( peak < StartCompression ) return color;
	float d = 1. - StartCompression;
	float newPeak = 1. - d * d / ( peak + d - StartCompression );
	color *= newPeak / peak;
	float g = 1. - 1. / ( Desaturation * ( peak - newPeak ) + 1. );
	return mix( color, vec3( newPeak ), g );
}
vec3 CustomToneMapping( vec3 color ) { return color; }`,ml=`#ifdef USE_TRANSMISSION
	material.transmission = transmission;
	material.transmissionAlpha = 1.0;
	material.thickness = thickness;
	material.attenuationDistance = attenuationDistance;
	material.attenuationColor = attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		material.transmission *= texture2D( transmissionMap, vTransmissionMapUv ).r;
	#endif
	#ifdef USE_THICKNESSMAP
		material.thickness *= texture2D( thicknessMap, vThicknessMapUv ).g;
	#endif
	vec3 pos = vWorldPosition;
	vec3 v = normalize( cameraPosition - pos );
	vec3 n = transformNormalByInverseViewMatrix( normal, viewMatrix );
	vec4 transmitted = getIBLVolumeRefraction(
		n, v, material.roughness, material.diffuseContribution, material.specularColorBlended, material.specularF90,
		pos, modelMatrix, viewMatrix, projectionMatrix, material.dispersion, material.ior, material.thickness,
		material.attenuationColor, material.attenuationDistance );
	material.transmissionAlpha = mix( material.transmissionAlpha, transmitted.a, material.transmission );
	totalDiffuse = mix( totalDiffuse, transmitted.rgb, material.transmission );
#endif`,_l=`#ifdef USE_TRANSMISSION
	uniform float transmission;
	uniform float thickness;
	uniform float attenuationDistance;
	uniform vec3 attenuationColor;
	#ifdef USE_TRANSMISSIONMAP
		uniform sampler2D transmissionMap;
	#endif
	#ifdef USE_THICKNESSMAP
		uniform sampler2D thicknessMap;
	#endif
	uniform vec2 transmissionSamplerSize;
	uniform sampler2D transmissionSamplerMap;
	uniform mat4 modelMatrix;
	uniform mat4 projectionMatrix;
	varying vec3 vWorldPosition;
	float w0( float a ) {
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - a + 3.0 ) - 3.0 ) + 1.0 );
	}
	float w1( float a ) {
		return ( 1.0 / 6.0 ) * ( a *  a * ( 3.0 * a - 6.0 ) + 4.0 );
	}
	float w2( float a ){
		return ( 1.0 / 6.0 ) * ( a * ( a * ( - 3.0 * a + 3.0 ) + 3.0 ) + 1.0 );
	}
	float w3( float a ) {
		return ( 1.0 / 6.0 ) * ( a * a * a );
	}
	float g0( float a ) {
		return w0( a ) + w1( a );
	}
	float g1( float a ) {
		return w2( a ) + w3( a );
	}
	float h0( float a ) {
		return - 1.0 + w1( a ) / ( w0( a ) + w1( a ) );
	}
	float h1( float a ) {
		return 1.0 + w3( a ) / ( w2( a ) + w3( a ) );
	}
	vec4 bicubic( sampler2D tex, vec2 uv, vec4 texelSize, float lod ) {
		uv = uv * texelSize.zw + 0.5;
		vec2 iuv = floor( uv );
		vec2 fuv = fract( uv );
		float g0x = g0( fuv.x );
		float g1x = g1( fuv.x );
		float h0x = h0( fuv.x );
		float h1x = h1( fuv.x );
		float h0y = h0( fuv.y );
		float h1y = h1( fuv.y );
		vec2 p0 = ( vec2( iuv.x + h0x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p1 = ( vec2( iuv.x + h1x, iuv.y + h0y ) - 0.5 ) * texelSize.xy;
		vec2 p2 = ( vec2( iuv.x + h0x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		vec2 p3 = ( vec2( iuv.x + h1x, iuv.y + h1y ) - 0.5 ) * texelSize.xy;
		return g0( fuv.y ) * ( g0x * textureLod( tex, p0, lod ) + g1x * textureLod( tex, p1, lod ) ) +
			g1( fuv.y ) * ( g0x * textureLod( tex, p2, lod ) + g1x * textureLod( tex, p3, lod ) );
	}
	vec4 textureBicubic( sampler2D sampler, vec2 uv, float lod ) {
		vec2 fLodSize = vec2( textureSize( sampler, int( lod ) ) );
		vec2 cLodSize = vec2( textureSize( sampler, int( lod + 1.0 ) ) );
		vec2 fLodSizeInv = 1.0 / fLodSize;
		vec2 cLodSizeInv = 1.0 / cLodSize;
		vec4 fSample = bicubic( sampler, uv, vec4( fLodSizeInv, fLodSize ), floor( lod ) );
		vec4 cSample = bicubic( sampler, uv, vec4( cLodSizeInv, cLodSize ), ceil( lod ) );
		return mix( fSample, cSample, fract( lod ) );
	}
	vec3 getVolumeTransmissionRay( const in vec3 n, const in vec3 v, const in float thickness, const in float ior, const in mat4 modelMatrix ) {
		vec3 refractionVector = refract( - v, normalize( n ), 1.0 / ior );
		vec3 modelScale;
		modelScale.x = length( vec3( modelMatrix[ 0 ].xyz ) );
		modelScale.y = length( vec3( modelMatrix[ 1 ].xyz ) );
		modelScale.z = length( vec3( modelMatrix[ 2 ].xyz ) );
		return normalize( refractionVector ) * thickness * modelScale;
	}
	float applyIorToRoughness( const in float roughness, const in float ior ) {
		return roughness * clamp( ior * 2.0 - 2.0, 0.0, 1.0 );
	}
	vec4 getTransmissionSample( const in vec2 fragCoord, const in float roughness, const in float ior ) {
		float lod = log2( transmissionSamplerSize.x ) * applyIorToRoughness( roughness, ior );
		return textureBicubic( transmissionSamplerMap, fragCoord.xy, lod );
	}
	vec3 volumeAttenuation( const in float transmissionDistance, const in vec3 attenuationColor, const in float attenuationDistance ) {
		if ( isinf( attenuationDistance ) ) {
			return vec3( 1.0 );
		} else {
			vec3 attenuationCoefficient = -log( attenuationColor ) / attenuationDistance;
			vec3 transmittance = exp( - attenuationCoefficient * transmissionDistance );			return transmittance;
		}
	}
	vec4 getIBLVolumeRefraction( const in vec3 n, const in vec3 v, const in float roughness, const in vec3 diffuseColor,
		const in vec3 specularColor, const in float specularF90, const in vec3 position, const in mat4 modelMatrix,
		const in mat4 viewMatrix, const in mat4 projMatrix, const in float dispersion, const in float ior, const in float thickness,
		const in vec3 attenuationColor, const in float attenuationDistance ) {
		vec4 transmittedLight;
		vec3 transmittance;
		#ifdef USE_DISPERSION
			float halfSpread = ( ior - 1.0 ) * 0.025 * dispersion;
			vec3 iors = vec3( ior - halfSpread, ior, ior + halfSpread );
			for ( int i = 0; i < 3; i ++ ) {
				vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, iors[ i ], modelMatrix );
				vec3 refractedRayExit = position + transmissionRay;
				vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
				vec2 refractionCoords = ndcPos.xy / ndcPos.w;
				refractionCoords += 1.0;
				refractionCoords /= 2.0;
				vec4 transmissionSample = getTransmissionSample( refractionCoords, roughness, iors[ i ] );
				transmittedLight[ i ] = transmissionSample[ i ];
				transmittedLight.a += transmissionSample.a;
				transmittance[ i ] = diffuseColor[ i ] * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance )[ i ];
			}
			transmittedLight.a /= 3.0;
		#else
			vec3 transmissionRay = getVolumeTransmissionRay( n, v, thickness, ior, modelMatrix );
			vec3 refractedRayExit = position + transmissionRay;
			vec4 ndcPos = projMatrix * viewMatrix * vec4( refractedRayExit, 1.0 );
			vec2 refractionCoords = ndcPos.xy / ndcPos.w;
			refractionCoords += 1.0;
			refractionCoords /= 2.0;
			transmittedLight = getTransmissionSample( refractionCoords, roughness, ior );
			transmittance = diffuseColor * volumeAttenuation( length( transmissionRay ), attenuationColor, attenuationDistance );
		#endif
		vec3 attenuatedColor = transmittance * transmittedLight.rgb;
		vec3 F = EnvironmentBRDF( n, v, specularColor, specularF90, roughness );
		float transmittanceFactor = ( transmittance.r + transmittance.g + transmittance.b ) / 3.0;
		return vec4( ( 1.0 - F ) * attenuatedColor, 1.0 - ( 1.0 - transmittedLight.a ) * transmittanceFactor );
	}
#endif`,gl=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_SPECULARMAP
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,vl=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	varying vec2 vUv;
#endif
#ifdef USE_MAP
	uniform mat3 mapTransform;
	varying vec2 vMapUv;
#endif
#ifdef USE_ALPHAMAP
	uniform mat3 alphaMapTransform;
	varying vec2 vAlphaMapUv;
#endif
#ifdef USE_LIGHTMAP
	uniform mat3 lightMapTransform;
	varying vec2 vLightMapUv;
#endif
#ifdef USE_AOMAP
	uniform mat3 aoMapTransform;
	varying vec2 vAoMapUv;
#endif
#ifdef USE_BUMPMAP
	uniform mat3 bumpMapTransform;
	varying vec2 vBumpMapUv;
#endif
#ifdef USE_NORMALMAP
	uniform mat3 normalMapTransform;
	varying vec2 vNormalMapUv;
#endif
#ifdef USE_DISPLACEMENTMAP
	uniform mat3 displacementMapTransform;
	varying vec2 vDisplacementMapUv;
#endif
#ifdef USE_EMISSIVEMAP
	uniform mat3 emissiveMapTransform;
	varying vec2 vEmissiveMapUv;
#endif
#ifdef USE_METALNESSMAP
	uniform mat3 metalnessMapTransform;
	varying vec2 vMetalnessMapUv;
#endif
#ifdef USE_ROUGHNESSMAP
	uniform mat3 roughnessMapTransform;
	varying vec2 vRoughnessMapUv;
#endif
#ifdef USE_ANISOTROPYMAP
	uniform mat3 anisotropyMapTransform;
	varying vec2 vAnisotropyMapUv;
#endif
#ifdef USE_CLEARCOATMAP
	uniform mat3 clearcoatMapTransform;
	varying vec2 vClearcoatMapUv;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	uniform mat3 clearcoatNormalMapTransform;
	varying vec2 vClearcoatNormalMapUv;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	uniform mat3 clearcoatRoughnessMapTransform;
	varying vec2 vClearcoatRoughnessMapUv;
#endif
#ifdef USE_SHEEN_COLORMAP
	uniform mat3 sheenColorMapTransform;
	varying vec2 vSheenColorMapUv;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	uniform mat3 sheenRoughnessMapTransform;
	varying vec2 vSheenRoughnessMapUv;
#endif
#ifdef USE_IRIDESCENCEMAP
	uniform mat3 iridescenceMapTransform;
	varying vec2 vIridescenceMapUv;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	uniform mat3 iridescenceThicknessMapTransform;
	varying vec2 vIridescenceThicknessMapUv;
#endif
#ifdef USE_SPECULARMAP
	uniform mat3 specularMapTransform;
	varying vec2 vSpecularMapUv;
#endif
#ifdef USE_SPECULAR_COLORMAP
	uniform mat3 specularColorMapTransform;
	varying vec2 vSpecularColorMapUv;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	uniform mat3 specularIntensityMapTransform;
	varying vec2 vSpecularIntensityMapUv;
#endif
#ifdef USE_TRANSMISSIONMAP
	uniform mat3 transmissionMapTransform;
	varying vec2 vTransmissionMapUv;
#endif
#ifdef USE_THICKNESSMAP
	uniform mat3 thicknessMapTransform;
	varying vec2 vThicknessMapUv;
#endif`,Sl=`#if defined( USE_UV ) || defined( USE_ANISOTROPY )
	vUv = vec3( uv, 1 ).xy;
#endif
#ifdef USE_MAP
	vMapUv = ( mapTransform * vec3( MAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ALPHAMAP
	vAlphaMapUv = ( alphaMapTransform * vec3( ALPHAMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_LIGHTMAP
	vLightMapUv = ( lightMapTransform * vec3( LIGHTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_AOMAP
	vAoMapUv = ( aoMapTransform * vec3( AOMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_BUMPMAP
	vBumpMapUv = ( bumpMapTransform * vec3( BUMPMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_NORMALMAP
	vNormalMapUv = ( normalMapTransform * vec3( NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_DISPLACEMENTMAP
	vDisplacementMapUv = ( displacementMapTransform * vec3( DISPLACEMENTMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_EMISSIVEMAP
	vEmissiveMapUv = ( emissiveMapTransform * vec3( EMISSIVEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_METALNESSMAP
	vMetalnessMapUv = ( metalnessMapTransform * vec3( METALNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ROUGHNESSMAP
	vRoughnessMapUv = ( roughnessMapTransform * vec3( ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_ANISOTROPYMAP
	vAnisotropyMapUv = ( anisotropyMapTransform * vec3( ANISOTROPYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOATMAP
	vClearcoatMapUv = ( clearcoatMapTransform * vec3( CLEARCOATMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_NORMALMAP
	vClearcoatNormalMapUv = ( clearcoatNormalMapTransform * vec3( CLEARCOAT_NORMALMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_CLEARCOAT_ROUGHNESSMAP
	vClearcoatRoughnessMapUv = ( clearcoatRoughnessMapTransform * vec3( CLEARCOAT_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCEMAP
	vIridescenceMapUv = ( iridescenceMapTransform * vec3( IRIDESCENCEMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_IRIDESCENCE_THICKNESSMAP
	vIridescenceThicknessMapUv = ( iridescenceThicknessMapTransform * vec3( IRIDESCENCE_THICKNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_COLORMAP
	vSheenColorMapUv = ( sheenColorMapTransform * vec3( SHEEN_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SHEEN_ROUGHNESSMAP
	vSheenRoughnessMapUv = ( sheenRoughnessMapTransform * vec3( SHEEN_ROUGHNESSMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULARMAP
	vSpecularMapUv = ( specularMapTransform * vec3( SPECULARMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_COLORMAP
	vSpecularColorMapUv = ( specularColorMapTransform * vec3( SPECULAR_COLORMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_SPECULAR_INTENSITYMAP
	vSpecularIntensityMapUv = ( specularIntensityMapTransform * vec3( SPECULAR_INTENSITYMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_TRANSMISSIONMAP
	vTransmissionMapUv = ( transmissionMapTransform * vec3( TRANSMISSIONMAP_UV, 1 ) ).xy;
#endif
#ifdef USE_THICKNESSMAP
	vThicknessMapUv = ( thicknessMapTransform * vec3( THICKNESSMAP_UV, 1 ) ).xy;
#endif`,El=`#if defined( USE_ENVMAP ) || defined( DISTANCE ) || defined ( USE_SHADOWMAP ) || defined ( USE_TRANSMISSION ) || NUM_SPOT_LIGHT_COORDS > 0
	vec4 worldPosition = vec4( transformed, 1.0 );
	#ifdef USE_BATCHING
		worldPosition = batchingMatrix * worldPosition;
	#endif
	#ifdef USE_INSTANCING
		worldPosition = instanceMatrix * worldPosition;
	#endif
	worldPosition = modelMatrix * worldPosition;
#endif`;const xl=`varying vec2 vUv;
uniform mat3 uvTransform;
void main() {
	vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	gl_Position = vec4( position.xy, 1.0, 1.0 );
}`,Ml=`uniform sampler2D t2D;
uniform float backgroundIntensity;
varying vec2 vUv;
void main() {
	vec4 texColor = texture2D( t2D, vUv );
	#ifdef DECODE_VIDEO_TEXTURE
		texColor = vec4( mix( pow( texColor.rgb * 0.9478672986 + vec3( 0.0521327014 ), vec3( 2.4 ) ), texColor.rgb * 0.0773993808, vec3( lessThanEqual( texColor.rgb, vec3( 0.04045 ) ) ) ), texColor.w );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,Tl=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,Al=`#ifdef ENVMAP_TYPE_CUBE
	uniform samplerCube envMap;
#elif defined( ENVMAP_TYPE_CUBE_UV )
	uniform sampler2D envMap;
#endif
uniform float backgroundBlurriness;
uniform float backgroundIntensity;
uniform mat3 backgroundRotation;
varying vec3 vWorldDirection;
#include <cube_uv_reflection_fragment>
void main() {
	#ifdef ENVMAP_TYPE_CUBE
		vec4 texColor = textureCube( envMap, backgroundRotation * vWorldDirection );
	#elif defined( ENVMAP_TYPE_CUBE_UV )
		vec4 texColor = textureCubeUV( envMap, backgroundRotation * vWorldDirection, backgroundBlurriness );
	#else
		vec4 texColor = vec4( 0.0, 0.0, 0.0, 1.0 );
	#endif
	texColor.rgb *= backgroundIntensity;
	gl_FragColor = texColor;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,Rl=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
	gl_Position.z = gl_Position.w;
}`,bl=`uniform samplerCube tCube;
uniform float tFlip;
uniform float opacity;
varying vec3 vWorldDirection;
void main() {
	vec4 texColor = textureCube( tCube, vec3( tFlip * vWorldDirection.x, vWorldDirection.yz ) );
	gl_FragColor = texColor;
	gl_FragColor.a *= opacity;
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,Cl=`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
varying vec2 vHighPrecisionZW;
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vHighPrecisionZW = gl_Position.zw;
}`,Pl=`#if DEPTH_PACKING == 3200
	uniform float opacity;
#endif
#include <common>
#include <packing>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
varying vec2 vHighPrecisionZW;
void main() {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#if DEPTH_PACKING == 3200
		diffuseColor.a = opacity;
	#endif
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <logdepthbuf_fragment>
	#ifdef USE_REVERSED_DEPTH_BUFFER
		float fragCoordZ = vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ];
	#else
		float fragCoordZ = 0.5 * vHighPrecisionZW[ 0 ] / vHighPrecisionZW[ 1 ] + 0.5;
	#endif
	#if DEPTH_PACKING == 3200
		gl_FragColor = vec4( vec3( 1.0 - fragCoordZ ), opacity );
	#elif DEPTH_PACKING == 3201
		gl_FragColor = packDepthToRGBA( fragCoordZ );
	#elif DEPTH_PACKING == 3202
		gl_FragColor = vec4( packDepthToRGB( fragCoordZ ), 1.0 );
	#elif DEPTH_PACKING == 3203
		gl_FragColor = vec4( packDepthToRG( fragCoordZ ), 0.0, 1.0 );
	#endif
}`,Ll=`#define DISTANCE
varying vec3 vWorldPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <skinbase_vertex>
	#include <morphinstance_vertex>
	#ifdef USE_DISPLACEMENTMAP
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <worldpos_vertex>
	#include <clipping_planes_vertex>
	vWorldPosition = worldPosition.xyz;
}`,Ul=`#define DISTANCE
uniform vec3 referencePosition;
uniform float nearDistance;
uniform float farDistance;
varying vec3 vWorldPosition;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( 1.0 );
	#include <clipping_planes_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	float dist = length( vWorldPosition - referencePosition );
	dist = ( dist - nearDistance ) / ( farDistance - nearDistance );
	dist = saturate( dist );
	gl_FragColor = vec4( dist, 0.0, 0.0, 1.0 );
}`,wl=`varying vec3 vWorldDirection;
#include <common>
void main() {
	vWorldDirection = transformDirection( position, modelMatrix );
	#include <begin_vertex>
	#include <project_vertex>
}`,Dl=`uniform sampler2D tEquirect;
varying vec3 vWorldDirection;
#include <common>
void main() {
	vec3 direction = normalize( vWorldDirection );
	vec2 sampleUV = equirectUv( direction );
	gl_FragColor = texture2D( tEquirect, sampleUV );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
}`,Il=`uniform float scale;
attribute float lineDistance;
varying float vLineDistance;
#include <common>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	vLineDistance = scale * lineDistance;
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,Nl=`uniform vec3 diffuse;
uniform float opacity;
uniform float dashSize;
uniform float totalSize;
varying float vLineDistance;
#include <common>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	if ( mod( vLineDistance, totalSize ) > dashSize ) {
		discard;
	}
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,yl=`#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#if defined ( USE_ENVMAP ) || defined ( USE_SKINNING )
		#include <beginnormal_vertex>
		#include <morphnormal_vertex>
		#include <skinbase_vertex>
		#include <skinnormal_vertex>
		#include <defaultnormal_vertex>
	#endif
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <fog_vertex>
}`,Fl=`uniform vec3 diffuse;
uniform float opacity;
#ifndef FLAT_SHADED
	varying vec3 vNormal;
#endif
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <fog_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	#ifdef USE_LIGHTMAP
		vec4 lightMapTexel = texture2D( lightMap, vLightMapUv );
		reflectedLight.indirectDiffuse += lightMapTexel.rgb * lightMapIntensity * RECIPROCAL_PI;
	#else
		reflectedLight.indirectDiffuse += vec3( 1.0 );
	#endif
	#include <aomap_fragment>
	reflectedLight.indirectDiffuse *= diffuseColor.rgb;
	vec3 outgoingLight = reflectedLight.indirectDiffuse;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Ol=`#define LAMBERT
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,Bl=`#define LAMBERT
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_lambert_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_lambert_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Gl=`#define MATCAP
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <color_pars_vertex>
#include <displacementmap_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
	vViewPosition = - mvPosition.xyz;
}`,Hl=`#define MATCAP
uniform vec3 diffuse;
uniform float opacity;
uniform sampler2D matcap;
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	vec3 viewDir = normalize( vViewPosition );
	vec3 x = normalize( vec3( viewDir.z, 0.0, - viewDir.x ) );
	vec3 y = cross( viewDir, x );
	vec2 uv = vec2( dot( x, normal ), dot( y, normal ) ) * 0.495 + 0.5;
	#ifdef USE_MATCAP
		vec4 matcapColor = texture2D( matcap, uv );
	#else
		vec4 matcapColor = vec4( vec3( mix( 0.2, 0.8, uv.y ) ), 1.0 );
	#endif
	vec3 outgoingLight = diffuseColor.rgb * matcapColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Vl=`#define NORMAL
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	vViewPosition = - mvPosition.xyz;
#endif
}`,Wl=`#define NORMAL
uniform float opacity;
#if defined( FLAT_SHADED ) || defined( USE_BUMPMAP ) || defined( USE_NORMALMAP_TANGENTSPACE )
	varying vec3 vViewPosition;
#endif
#include <uv_pars_fragment>
#include <normal_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( 0.0, 0.0, 0.0, opacity );
	#include <clipping_planes_fragment>
	#include <logdepthbuf_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	gl_FragColor = vec4( normalize( normal ) * 0.5 + 0.5, diffuseColor.a );
	#ifdef OPAQUE
		gl_FragColor.a = 1.0;
	#endif
}`,kl=`#define PHONG
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <envmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <envmap_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,zl=`#define PHONG
uniform vec3 diffuse;
uniform vec3 emissive;
uniform vec3 specular;
uniform float shininess;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_phong_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <specularmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <specularmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_phong_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + reflectedLight.directSpecular + reflectedLight.indirectSpecular + totalEmissiveRadiance;
	#include <envmap_fragment>
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Xl=`#define STANDARD
varying vec3 vViewPosition;
#ifdef USE_TRANSMISSION
	varying vec3 vWorldPosition;
#endif
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
#ifdef USE_TRANSMISSION
	vWorldPosition = worldPosition.xyz;
#endif
}`,Yl=`#define STANDARD
#ifdef PHYSICAL
	#define IOR
	#define USE_SPECULAR
#endif
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float roughness;
uniform float metalness;
uniform float opacity;
#ifdef IOR
	uniform float ior;
#endif
#ifdef USE_SPECULAR
	uniform float specularIntensity;
	uniform vec3 specularColor;
	#ifdef USE_SPECULAR_COLORMAP
		uniform sampler2D specularColorMap;
	#endif
	#ifdef USE_SPECULAR_INTENSITYMAP
		uniform sampler2D specularIntensityMap;
	#endif
#endif
#ifdef USE_CLEARCOAT
	uniform float clearcoat;
	uniform float clearcoatRoughness;
#endif
#ifdef USE_DISPERSION
	uniform float dispersion;
#endif
#ifdef USE_RETROREFLECTION
	uniform float retroreflectivity;
#endif
#ifdef USE_IRIDESCENCE
	uniform float iridescence;
	uniform float iridescenceIOR;
	uniform float iridescenceThicknessMinimum;
	uniform float iridescenceThicknessMaximum;
#endif
#ifdef USE_SHEEN
	uniform vec3 sheenColor;
	uniform float sheenRoughness;
	#ifdef USE_SHEEN_COLORMAP
		uniform sampler2D sheenColorMap;
	#endif
	#ifdef USE_SHEEN_ROUGHNESSMAP
		uniform sampler2D sheenRoughnessMap;
	#endif
#endif
#ifdef USE_ANISOTROPY
	uniform vec2 anisotropyVector;
	#ifdef USE_ANISOTROPYMAP
		uniform sampler2D anisotropyMap;
	#endif
#endif
varying vec3 vViewPosition;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <iridescence_fragment>
#include <cube_uv_reflection_fragment>
#include <envmap_common_pars_fragment>
#include <envmap_physical_pars_fragment>
#include <fog_pars_fragment>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_physical_pars_fragment>
#include <transmission_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <clearcoat_pars_fragment>
#include <iridescence_pars_fragment>
#include <roughnessmap_pars_fragment>
#include <metalnessmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <roughnessmap_fragment>
	#include <metalnessmap_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <clearcoat_normal_fragment_begin>
	#include <clearcoat_normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_physical_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 totalDiffuse = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse;
	vec3 totalSpecular = reflectedLight.directSpecular + reflectedLight.indirectSpecular;
	#include <transmission_fragment>
	vec3 outgoingLight = totalDiffuse + totalSpecular + totalEmissiveRadiance;
	#ifdef USE_SHEEN
 
		outgoingLight = outgoingLight + sheenSpecularDirect + sheenSpecularIndirect;
 
 	#endif
	#ifdef USE_CLEARCOAT
		float dotNVcc = saturate( dot( geometryClearcoatNormal, geometryViewDir ) );
		vec3 Fcc = F_Schlick( material.clearcoatF0, material.clearcoatF90, dotNVcc );
		outgoingLight = outgoingLight * ( 1.0 - material.clearcoat * Fcc ) + ( clearcoatSpecularDirect + clearcoatSpecularIndirect ) * material.clearcoat;
	#endif
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Kl=`#define TOON
varying vec3 vViewPosition;
#include <common>
#include <batching_pars_vertex>
#include <uv_pars_vertex>
#include <displacementmap_pars_vertex>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <normal_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <shadowmap_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <normal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <displacementmap_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	vViewPosition = - mvPosition.xyz;
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,ql=`#define TOON
uniform vec3 diffuse;
uniform vec3 emissive;
uniform float opacity;
#include <common>
#include <dithering_pars_fragment>
#include <color_pars_fragment>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <aomap_pars_fragment>
#include <lightmap_pars_fragment>
#include <emissivemap_pars_fragment>
#include <gradientmap_pars_fragment>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <normal_pars_fragment>
#include <lights_toon_pars_fragment>
#include <shadowmap_pars_fragment>
#include <bumpmap_pars_fragment>
#include <normalmap_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	ReflectedLight reflectedLight = ReflectedLight( vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ), vec3( 0.0 ) );
	vec3 totalEmissiveRadiance = emissive;
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <color_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	#include <normal_fragment_begin>
	#include <normal_fragment_maps>
	#include <emissivemap_fragment>
	#include <lights_toon_fragment>
	#include <lights_fragment_begin>
	#include <lights_fragment_maps>
	#include <lights_fragment_end>
	#include <aomap_fragment>
	vec3 outgoingLight = reflectedLight.directDiffuse + reflectedLight.indirectDiffuse + totalEmissiveRadiance;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
	#include <dithering_fragment>
}`,Zl=`uniform float size;
uniform float scale;
#include <common>
#include <color_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
#ifdef USE_POINTS_UV
	varying vec2 vUv;
	uniform mat3 uvTransform;
#endif
void main() {
	#ifdef USE_POINTS_UV
		vUv = ( uvTransform * vec3( uv, 1 ) ).xy;
	#endif
	#include <color_vertex>
	#include <morphinstance_vertex>
	#include <morphcolor_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <project_vertex>
	gl_PointSize = size;
	#ifdef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) gl_PointSize *= ( scale / - mvPosition.z );
	#endif
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <worldpos_vertex>
	#include <fog_vertex>
}`,$l=`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <color_pars_fragment>
#include <map_particle_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_particle_fragment>
	#include <color_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,Ql=`#include <common>
#include <batching_pars_vertex>
#include <fog_pars_vertex>
#include <morphtarget_pars_vertex>
#include <skinning_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <shadowmap_pars_vertex>
void main() {
	#include <batching_vertex>
	#include <beginnormal_vertex>
	#include <morphinstance_vertex>
	#include <morphnormal_vertex>
	#include <skinbase_vertex>
	#include <skinnormal_vertex>
	#include <defaultnormal_vertex>
	#include <begin_vertex>
	#include <morphtarget_vertex>
	#include <skinning_vertex>
	#include <project_vertex>
	#include <logdepthbuf_vertex>
	#include <worldpos_vertex>
	#include <shadowmap_vertex>
	#include <fog_vertex>
}`,Jl=`uniform vec3 color;
uniform float opacity;
#include <common>
#include <fog_pars_fragment>
#include <bsdfs>
#include <lights_pars_begin>
#include <logdepthbuf_pars_fragment>
#include <shadowmap_pars_fragment>
#include <shadowmask_pars_fragment>
void main() {
	#include <logdepthbuf_fragment>
	gl_FragColor = vec4( color, opacity * ( 1.0 - getShadowMask() ) );
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
	#include <premultiplied_alpha_fragment>
}`,jl=`uniform float rotation;
uniform vec2 center;
#include <common>
#include <uv_pars_vertex>
#include <fog_pars_vertex>
#include <logdepthbuf_pars_vertex>
#include <clipping_planes_pars_vertex>
void main() {
	#include <uv_vertex>
	vec4 mvPosition = modelViewMatrix[ 3 ];
	vec2 scale = vec2( length( modelMatrix[ 0 ].xyz ), length( modelMatrix[ 1 ].xyz ) );
	#ifndef USE_SIZEATTENUATION
		bool isPerspective = isPerspectiveMatrix( projectionMatrix );
		if ( isPerspective ) scale *= - mvPosition.z;
	#endif
	vec2 alignedPosition = ( position.xy - ( center - vec2( 0.5 ) ) ) * scale;
	vec2 rotatedPosition;
	rotatedPosition.x = cos( rotation ) * alignedPosition.x - sin( rotation ) * alignedPosition.y;
	rotatedPosition.y = sin( rotation ) * alignedPosition.x + cos( rotation ) * alignedPosition.y;
	mvPosition.xy += rotatedPosition;
	gl_Position = projectionMatrix * mvPosition;
	#include <logdepthbuf_vertex>
	#include <clipping_planes_vertex>
	#include <fog_vertex>
}`,ec=`uniform vec3 diffuse;
uniform float opacity;
#include <common>
#include <uv_pars_fragment>
#include <map_pars_fragment>
#include <alphamap_pars_fragment>
#include <alphatest_pars_fragment>
#include <alphahash_pars_fragment>
#include <fog_pars_fragment>
#include <logdepthbuf_pars_fragment>
#include <clipping_planes_pars_fragment>
void main() {
	vec4 diffuseColor = vec4( diffuse, opacity );
	#include <clipping_planes_fragment>
	vec3 outgoingLight = vec3( 0.0 );
	#include <logdepthbuf_fragment>
	#include <map_fragment>
	#include <alphamap_fragment>
	#include <alphatest_fragment>
	#include <alphahash_fragment>
	outgoingLight = diffuseColor.rgb;
	#include <opaque_fragment>
	#include <tonemapping_fragment>
	#include <colorspace_fragment>
	#include <fog_fragment>
}`,Le={alphahash_fragment:xo,alphahash_pars_fragment:Mo,alphamap_fragment:To,alphamap_pars_fragment:Ao,alphatest_fragment:Ro,alphatest_pars_fragment:bo,aomap_fragment:Co,aomap_pars_fragment:Po,batching_pars_vertex:Lo,batching_vertex:Uo,begin_vertex:wo,beginnormal_vertex:Do,bsdfs:Io,iridescence_fragment:No,bumpmap_pars_fragment:yo,clipping_planes_fragment:Fo,clipping_planes_pars_fragment:Oo,clipping_planes_pars_vertex:Bo,clipping_planes_vertex:Go,color_fragment:Ho,color_pars_fragment:Vo,color_pars_vertex:Wo,color_vertex:ko,common:zo,cube_uv_reflection_fragment:Xo,defaultnormal_vertex:Yo,displacementmap_pars_vertex:Ko,displacementmap_vertex:qo,emissivemap_fragment:Zo,emissivemap_pars_fragment:$o,colorspace_fragment:Qo,colorspace_pars_fragment:Jo,envmap_fragment:jo,envmap_common_pars_fragment:es,envmap_pars_fragment:ts,envmap_pars_vertex:ns,envmap_physical_pars_fragment:ps,envmap_vertex:is,fog_vertex:rs,fog_pars_vertex:as,fog_fragment:os,fog_pars_fragment:ss,gradientmap_pars_fragment:ls,lightmap_pars_fragment:cs,lights_lambert_fragment:fs,lights_lambert_pars_fragment:ds,lights_pars_begin:us,lights_toon_fragment:hs,lights_toon_pars_fragment:ms,lights_phong_fragment:_s,lights_phong_pars_fragment:gs,lights_physical_fragment:vs,lights_physical_pars_fragment:Ss,lights_fragment_begin:Es,lights_fragment_maps:xs,lights_fragment_end:Ms,lightprobes_pars_fragment:Ts,logdepthbuf_fragment:As,logdepthbuf_pars_fragment:Rs,logdepthbuf_pars_vertex:bs,logdepthbuf_vertex:Cs,map_fragment:Ps,map_pars_fragment:Ls,map_particle_fragment:Us,map_particle_pars_fragment:ws,metalnessmap_fragment:Ds,metalnessmap_pars_fragment:Is,morphinstance_vertex:Ns,morphcolor_vertex:ys,morphnormal_vertex:Fs,morphtarget_pars_vertex:Os,morphtarget_vertex:Bs,normal_fragment_begin:Gs,normal_fragment_maps:Hs,normal_pars_fragment:Vs,normal_pars_vertex:Ws,normal_vertex:ks,normalmap_pars_fragment:zs,clearcoat_normal_fragment_begin:Xs,clearcoat_normal_fragment_maps:Ys,clearcoat_pars_fragment:Ks,iridescence_pars_fragment:qs,opaque_fragment:Zs,packing:$s,premultiplied_alpha_fragment:Qs,project_vertex:Js,dithering_fragment:js,dithering_pars_fragment:el,roughnessmap_fragment:tl,roughnessmap_pars_fragment:nl,shadowmap_pars_fragment:il,shadowmap_pars_vertex:rl,shadowmap_vertex:al,shadowmask_pars_fragment:ol,skinbase_vertex:sl,skinning_pars_vertex:ll,skinning_vertex:cl,skinnormal_vertex:fl,specularmap_fragment:dl,specularmap_pars_fragment:ul,tonemapping_fragment:pl,tonemapping_pars_fragment:hl,transmission_fragment:ml,transmission_pars_fragment:_l,uv_pars_fragment:gl,uv_pars_vertex:vl,uv_vertex:Sl,worldpos_vertex:El,background_vert:xl,background_frag:Ml,backgroundCube_vert:Tl,backgroundCube_frag:Al,cube_vert:Rl,cube_frag:bl,depth_vert:Cl,depth_frag:Pl,distance_vert:Ll,distance_frag:Ul,equirect_vert:wl,equirect_frag:Dl,linedashed_vert:Il,linedashed_frag:Nl,meshbasic_vert:yl,meshbasic_frag:Fl,meshlambert_vert:Ol,meshlambert_frag:Bl,meshmatcap_vert:Gl,meshmatcap_frag:Hl,meshnormal_vert:Vl,meshnormal_frag:Wl,meshphong_vert:kl,meshphong_frag:zl,meshphysical_vert:Xl,meshphysical_frag:Yl,meshtoon_vert:Kl,meshtoon_frag:ql,points_vert:Zl,points_frag:$l,shadow_vert:Ql,shadow_frag:Jl,sprite_vert:jl,sprite_frag:ec},ce={common:{diffuse:{value:new et(16777215)},opacity:{value:1},map:{value:null},mapTransform:{value:new Fe},alphaMap:{value:null},alphaMapTransform:{value:new Fe},alphaTest:{value:0}},specularmap:{specularMap:{value:null},specularMapTransform:{value:new Fe}},envmap:{envMap:{value:null},envMapRotation:{value:new Fe},reflectivity:{value:1},ior:{value:1.5},refractionRatio:{value:.98},dfgLUT:{value:null}},aomap:{aoMap:{value:null},aoMapIntensity:{value:1},aoMapTransform:{value:new Fe}},lightmap:{lightMap:{value:null},lightMapIntensity:{value:1},lightMapTransform:{value:new Fe}},bumpmap:{bumpMap:{value:null},bumpMapTransform:{value:new Fe},bumpScale:{value:1}},normalmap:{normalMap:{value:null},normalMapTransform:{value:new Fe},normalScale:{value:new gt(1,1)}},displacementmap:{displacementMap:{value:null},displacementMapTransform:{value:new Fe},displacementScale:{value:1},displacementBias:{value:0}},emissivemap:{emissiveMap:{value:null},emissiveMapTransform:{value:new Fe}},metalnessmap:{metalnessMap:{value:null},metalnessMapTransform:{value:new Fe}},roughnessmap:{roughnessMap:{value:null},roughnessMapTransform:{value:new Fe}},gradientmap:{gradientMap:{value:null}},fog:{fogDensity:{value:25e-5},fogNear:{value:1},fogFar:{value:2e3},fogColor:{value:new et(16777215)}},lights:{ambientLightColor:{value:[]},lightProbe:{value:[]},sunLights:{value:[],properties:{direction:{},color:{}}},sunLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},sunShadowMatrix:{value:[]},sunShadowCascade:{value:[]},directionalLights:{value:[],properties:{direction:{},color:{}}},directionalLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},directionalShadowMatrix:{value:[]},spotLights:{value:[],properties:{color:{},position:{},direction:{},distance:{},coneCos:{},penumbraCos:{},decay:{}}},spotLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{}}},spotLightMap:{value:[]},spotLightMatrix:{value:[]},pointLights:{value:[],properties:{color:{},position:{},decay:{},distance:{}}},pointLightShadows:{value:[],properties:{shadowIntensity:1,shadowBias:{},shadowNormalBias:{},shadowRadius:{},shadowMapSize:{},shadowCameraNear:{},shadowCameraFar:{}}},pointShadowMatrix:{value:[]},hemisphereLights:{value:[],properties:{direction:{},skyColor:{},groundColor:{}}},rectAreaLights:{value:[],properties:{color:{},position:{},width:{},height:{}}},ltc_1:{value:null},ltc_2:{value:null},probesSH:{value:null},probesMin:{value:new Ne},probesMax:{value:new Ne},probesResolution:{value:new Ne}},points:{diffuse:{value:new et(16777215)},opacity:{value:1},size:{value:1},scale:{value:1},map:{value:null},alphaMap:{value:null},alphaMapTransform:{value:new Fe},alphaTest:{value:0},uvTransform:{value:new Fe}},sprite:{diffuse:{value:new et(16777215)},opacity:{value:1},center:{value:new gt(.5,.5)},rotation:{value:0},map:{value:null},mapTransform:{value:new Fe},alphaMap:{value:null},alphaMapTransform:{value:new Fe},alphaTest:{value:0}}},bt={basic:{uniforms:mt([ce.common,ce.specularmap,ce.envmap,ce.aomap,ce.lightmap,ce.fog]),vertexShader:Le.meshbasic_vert,fragmentShader:Le.meshbasic_frag},lambert:{uniforms:mt([ce.common,ce.specularmap,ce.envmap,ce.aomap,ce.lightmap,ce.emissivemap,ce.bumpmap,ce.normalmap,ce.displacementmap,ce.fog,ce.lights,{emissive:{value:new et(0)},envMapIntensity:{value:1}}]),vertexShader:Le.meshlambert_vert,fragmentShader:Le.meshlambert_frag},phong:{uniforms:mt([ce.common,ce.specularmap,ce.envmap,ce.aomap,ce.lightmap,ce.emissivemap,ce.bumpmap,ce.normalmap,ce.displacementmap,ce.fog,ce.lights,{emissive:{value:new et(0)},specular:{value:new et(1118481)},shininess:{value:30},envMapIntensity:{value:1}}]),vertexShader:Le.meshphong_vert,fragmentShader:Le.meshphong_frag},standard:{uniforms:mt([ce.common,ce.envmap,ce.aomap,ce.lightmap,ce.emissivemap,ce.bumpmap,ce.normalmap,ce.displacementmap,ce.roughnessmap,ce.metalnessmap,ce.fog,ce.lights,{emissive:{value:new et(0)},roughness:{value:1},metalness:{value:0},envMapIntensity:{value:1}}]),vertexShader:Le.meshphysical_vert,fragmentShader:Le.meshphysical_frag},toon:{uniforms:mt([ce.common,ce.aomap,ce.lightmap,ce.emissivemap,ce.bumpmap,ce.normalmap,ce.displacementmap,ce.gradientmap,ce.fog,ce.lights,{emissive:{value:new et(0)}}]),vertexShader:Le.meshtoon_vert,fragmentShader:Le.meshtoon_frag},matcap:{uniforms:mt([ce.common,ce.bumpmap,ce.normalmap,ce.displacementmap,ce.fog,{matcap:{value:null}}]),vertexShader:Le.meshmatcap_vert,fragmentShader:Le.meshmatcap_frag},points:{uniforms:mt([ce.points,ce.fog]),vertexShader:Le.points_vert,fragmentShader:Le.points_frag},dashed:{uniforms:mt([ce.common,ce.fog,{scale:{value:1},dashSize:{value:1},totalSize:{value:2}}]),vertexShader:Le.linedashed_vert,fragmentShader:Le.linedashed_frag},depth:{uniforms:mt([ce.common,ce.displacementmap]),vertexShader:Le.depth_vert,fragmentShader:Le.depth_frag},normal:{uniforms:mt([ce.common,ce.bumpmap,ce.normalmap,ce.displacementmap,{opacity:{value:1}}]),vertexShader:Le.meshnormal_vert,fragmentShader:Le.meshnormal_frag},sprite:{uniforms:mt([ce.sprite,ce.fog]),vertexShader:Le.sprite_vert,fragmentShader:Le.sprite_frag},background:{uniforms:{uvTransform:{value:new Fe},t2D:{value:null},backgroundIntensity:{value:1}},vertexShader:Le.background_vert,fragmentShader:Le.background_frag},backgroundCube:{uniforms:{envMap:{value:null},backgroundBlurriness:{value:0},backgroundIntensity:{value:1},backgroundRotation:{value:new Fe}},vertexShader:Le.backgroundCube_vert,fragmentShader:Le.backgroundCube_frag},cube:{uniforms:{tCube:{value:null},tFlip:{value:-1},opacity:{value:1}},vertexShader:Le.cube_vert,fragmentShader:Le.cube_frag},equirect:{uniforms:{tEquirect:{value:null}},vertexShader:Le.equirect_vert,fragmentShader:Le.equirect_frag},distance:{uniforms:mt([ce.common,ce.displacementmap,{referencePosition:{value:new Ne},nearDistance:{value:1},farDistance:{value:1e3}}]),vertexShader:Le.distance_vert,fragmentShader:Le.distance_frag},shadow:{uniforms:mt([ce.lights,ce.fog,{color:{value:new et(0)},opacity:{value:1}}]),vertexShader:Le.shadow_vert,fragmentShader:Le.shadow_frag}};bt.physical={uniforms:mt([bt.standard.uniforms,{clearcoat:{value:0},clearcoatMap:{value:null},clearcoatMapTransform:{value:new Fe},clearcoatNormalMap:{value:null},clearcoatNormalMapTransform:{value:new Fe},clearcoatNormalScale:{value:new gt(1,1)},clearcoatRoughness:{value:0},clearcoatRoughnessMap:{value:null},clearcoatRoughnessMapTransform:{value:new Fe},dispersion:{value:0},retroreflectivity:{value:0},iridescence:{value:0},iridescenceMap:{value:null},iridescenceMapTransform:{value:new Fe},iridescenceIOR:{value:1.3},iridescenceThicknessMinimum:{value:100},iridescenceThicknessMaximum:{value:400},iridescenceThicknessMap:{value:null},iridescenceThicknessMapTransform:{value:new Fe},sheen:{value:0},sheenColor:{value:new et(0)},sheenColorMap:{value:null},sheenColorMapTransform:{value:new Fe},sheenRoughness:{value:1},sheenRoughnessMap:{value:null},sheenRoughnessMapTransform:{value:new Fe},transmission:{value:0},transmissionMap:{value:null},transmissionMapTransform:{value:new Fe},transmissionSamplerSize:{value:new gt},transmissionSamplerMap:{value:null},thickness:{value:0},thicknessMap:{value:null},thicknessMapTransform:{value:new Fe},attenuationDistance:{value:0},attenuationColor:{value:new et(0)},specularColor:{value:new et(1,1,1)},specularColorMap:{value:null},specularColorMapTransform:{value:new Fe},specularIntensity:{value:1},specularIntensityMap:{value:null},specularIntensityMapTransform:{value:new Fe},anisotropyVector:{value:new gt},anisotropyMap:{value:null},anisotropyMapTransform:{value:new Fe}}]),vertexShader:Le.meshphysical_vert,fragmentShader:Le.meshphysical_frag};const pn={r:0,b:0,g:0},tc=new $t,Gr=new Fe;Gr.set(-1,0,0,0,1,0,0,0,1);function nc(e,n,t,i,l,o){const d=new et(0);let g=l===!0?0:1,R,T,H=null,I=0,p=null;function M(L){let z=L.isScene===!0?L.background:null;if(z&&z.isTexture){const h=L.backgroundBlurriness>0;z=n.get(z,h)}return z}function N(L){let z=!1;const h=M(L);h===null?f(d,g):h&&h.isColor&&(f(h,1),z=!0);const S=e.xr.getEnvironmentBlendMode();S==="additive"?t.buffers.color.setClear(0,0,0,1,o):S==="alpha-blend"&&t.buffers.color.setClear(0,0,0,0,o),(e.autoClear||z)&&(t.buffers.depth.setTest(!0),t.buffers.depth.setMask(!0),t.buffers.color.setMask(!0),e.clear(e.autoClearColor,e.autoClearDepth,e.autoClearStencil))}function W(L,z){const h=M(z);h&&(h.isCubeTexture||h.mapping===Mn)?(T===void 0&&(T=new Nt(new $n(1,1,1),new It({name:"BackgroundCubeMaterial",uniforms:kn(bt.backgroundCube.uniforms),vertexShader:bt.backgroundCube.vertexShader,fragmentShader:bt.backgroundCube.fragmentShader,side:St,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),T.geometry.deleteAttribute("normal"),T.geometry.deleteAttribute("uv"),T.onBeforeRender=function(S,m,w){this.matrixWorld.copyPosition(w.matrixWorld)},Object.defineProperty(T.material,"envMap",{get:function(){return this.uniforms.envMap.value}}),i.update(T)),T.material.uniforms.envMap.value=h,T.material.uniforms.backgroundBlurriness.value=z.backgroundBlurriness,T.material.uniforms.backgroundIntensity.value=z.backgroundIntensity,T.material.uniforms.backgroundRotation.value.setFromMatrix4(tc.makeRotationFromEuler(z.backgroundRotation)).transpose(),h.isCubeTexture&&h.isRenderTargetTexture===!1&&T.material.uniforms.backgroundRotation.value.premultiply(Gr),T.material.toneMapped=nt.getTransfer(h.colorSpace)!==$e,(H!==h||I!==h.version||p!==e.toneMapping)&&(T.material.needsUpdate=!0,H=h,I=h.version,p=e.toneMapping),T.layers.enableAll(),L.unshift(T,T.geometry,T.material,0,0,null)):h&&h.isTexture&&(R===void 0&&(R=new Nt(new Tr(2,2),new It({name:"BackgroundMaterial",uniforms:kn(bt.background.uniforms),vertexShader:bt.background.vertexShader,fragmentShader:bt.background.fragmentShader,side:sn,depthTest:!1,depthWrite:!1,fog:!1,allowOverride:!1})),R.geometry.deleteAttribute("normal"),Object.defineProperty(R.material,"map",{get:function(){return this.uniforms.t2D.value}}),i.update(R)),R.material.uniforms.t2D.value=h,R.material.uniforms.backgroundIntensity.value=z.backgroundIntensity,R.material.toneMapped=nt.getTransfer(h.colorSpace)!==$e,h.matrixAutoUpdate===!0&&h.updateMatrix(),R.material.uniforms.uvTransform.value.copy(h.matrix),(H!==h||I!==h.version||p!==e.toneMapping)&&(R.material.needsUpdate=!0,H=h,I=h.version,p=e.toneMapping),R.layers.enableAll(),L.unshift(R,R.geometry,R.material,0,0,null))}function f(L,z){L.getRGB(pn,Ar(e)),t.buffers.color.setClear(pn.r,pn.g,pn.b,z,o)}function s(){T!==void 0&&(T.geometry.dispose(),T.material.dispose(),T=void 0),R!==void 0&&(R.geometry.dispose(),R.material.dispose(),R=void 0)}return{getClearColor:function(){return d},setClearColor:function(L,z=1){d.set(L),g=z,f(d,g)},getClearAlpha:function(){return g},setClearAlpha:function(L){g=L,f(d,g)},render:N,addToRenderList:W,dispose:s}}function ic(e,n){const t=e.getParameter(e.MAX_VERTEX_ATTRIBS),i={},l=p(null);let o=l,d=!1;function g(F,G,q,P,Y){let Q=!1;const K=I(F,P,q,G);o!==K&&(o=K,T(o.object)),Q=M(F,P,q,Y),Q&&N(F,P,q,Y),Y!==null&&n.update(Y,e.ELEMENT_ARRAY_BUFFER),(Q||d)&&(d=!1,h(F,G,q,P),Y!==null&&e.bindBuffer(e.ELEMENT_ARRAY_BUFFER,n.get(Y).buffer))}function R(){return e.createVertexArray()}function T(F){return e.bindVertexArray(F)}function H(F){return e.deleteVertexArray(F)}function I(F,G,q,P){const Y=P.wireframe===!0;let Q=i[G.id];Q===void 0&&(Q={},i[G.id]=Q);const K=F.isInstancedMesh===!0?F.id:0;let ne=Q[K];ne===void 0&&(ne={},Q[K]=ne);let Z=ne[q.id];Z===void 0&&(Z={},ne[q.id]=Z);let j=Z[Y];return j===void 0&&(j=p(R()),Z[Y]=j),j}function p(F){const G=[],q=[],P=[];for(let Y=0;Y<t;Y++)G[Y]=0,q[Y]=0,P[Y]=0;return{geometry:null,program:null,wireframe:!1,newAttributes:G,enabledAttributes:q,attributeDivisors:P,object:F,attributes:{},index:null}}function M(F,G,q,P){const Y=o.attributes,Q=G.attributes;let K=0;const ne=q.getAttributes();for(const Z in ne)if(ne[Z].location>=0){const ee=Y[Z];let be=Q[Z];if(be===void 0&&(Z==="instanceMatrix"&&F.instanceMatrix&&(be=F.instanceMatrix),Z==="instanceColor"&&F.instanceColor&&(be=F.instanceColor)),ee===void 0||ee.attribute!==be||be&&ee.data!==be.data)return!0;K++}return o.attributesNum!==K||o.index!==P}function N(F,G,q,P){const Y={},Q=G.attributes;let K=0;const ne=q.getAttributes();for(const Z in ne)if(ne[Z].location>=0){let ee=Q[Z];ee===void 0&&(Z==="instanceMatrix"&&F.instanceMatrix&&(ee=F.instanceMatrix),Z==="instanceColor"&&F.instanceColor&&(ee=F.instanceColor));const be={};be.attribute=ee,ee&&ee.data&&(be.data=ee.data),Y[Z]=be,K++}o.attributes=Y,o.attributesNum=K,o.index=P}function W(){const F=o.newAttributes;for(let G=0,q=F.length;G<q;G++)F[G]=0}function f(F){s(F,0)}function s(F,G){const q=o.newAttributes,P=o.enabledAttributes,Y=o.attributeDivisors;q[F]=1,P[F]===0&&(e.enableVertexAttribArray(F),P[F]=1),Y[F]!==G&&(e.vertexAttribDivisor(F,G),Y[F]=G)}function L(){const F=o.newAttributes,G=o.enabledAttributes;for(let q=0,P=G.length;q<P;q++)G[q]!==F[q]&&(e.disableVertexAttribArray(q),G[q]=0)}function z(F,G,q,P,Y,Q,K){K===!0?e.vertexAttribIPointer(F,G,q,Y,Q):e.vertexAttribPointer(F,G,q,P,Y,Q)}function h(F,G,q,P){W();const Y=P.attributes,Q=q.getAttributes(),K=G.defaultAttributeValues;for(const ne in Q){const Z=Q[ne];if(Z.location>=0){let j=Y[ne];if(j===void 0&&(ne==="instanceMatrix"&&F.instanceMatrix&&(j=F.instanceMatrix),ne==="instanceColor"&&F.instanceColor&&(j=F.instanceColor)),j!==void 0){const ee=j.normalized,be=j.itemSize,Re=n.get(j);if(Re===void 0)continue;const it=Re.buffer,ke=Re.type,ze=Re.bytesPerElement,V=ke===e.INT||ke===e.UNSIGNED_INT||j.gpuType===Cr;if(j.isInterleavedBufferAttribute){const $=j.data,Ee=$.stride,Ue=j.offset;if($.isInstancedInterleavedBuffer){for(let me=0;me<Z.locationSize;me++)s(Z.location+me,$.meshPerAttribute);F.isInstancedMesh!==!0&&P._maxInstanceCount===void 0&&(P._maxInstanceCount=$.meshPerAttribute*$.count)}else for(let me=0;me<Z.locationSize;me++)f(Z.location+me);e.bindBuffer(e.ARRAY_BUFFER,it);for(let me=0;me<Z.locationSize;me++)z(Z.location+me,be/Z.locationSize,ke,ee,Ee*ze,(Ue+be/Z.locationSize*me)*ze,V)}else{if(j.isInstancedBufferAttribute){for(let $=0;$<Z.locationSize;$++)s(Z.location+$,j.meshPerAttribute);F.isInstancedMesh!==!0&&P._maxInstanceCount===void 0&&(P._maxInstanceCount=j.meshPerAttribute*j.count)}else for(let $=0;$<Z.locationSize;$++)f(Z.location+$);e.bindBuffer(e.ARRAY_BUFFER,it);for(let $=0;$<Z.locationSize;$++)z(Z.location+$,be/Z.locationSize,ke,ee,be*ze,be/Z.locationSize*$*ze,V)}}else if(K!==void 0){const ee=K[ne];if(ee!==void 0)switch(ee.length){case 2:e.vertexAttrib2fv(Z.location,ee);break;case 3:e.vertexAttrib3fv(Z.location,ee);break;case 4:e.vertexAttrib4fv(Z.location,ee);break;default:e.vertexAttrib1fv(Z.location,ee)}}}}L()}function S(){_();for(const F in i){const G=i[F];for(const q in G){const P=G[q];for(const Y in P){const Q=P[Y];for(const K in Q)H(Q[K].object),delete Q[K];delete P[Y]}}delete i[F]}}function m(F){if(i[F.id]===void 0)return;const G=i[F.id];for(const q in G){const P=G[q];for(const Y in P){const Q=P[Y];for(const K in Q)H(Q[K].object),delete Q[K];delete P[Y]}}delete i[F.id]}function w(F){for(const G in i){const q=i[G];for(const P in q){const Y=q[P];if(Y[F.id]===void 0)continue;const Q=Y[F.id];for(const K in Q)H(Q[K].object),delete Q[K];delete Y[F.id]}}}function c(F){for(const G in i){const q=i[G],P=F.isInstancedMesh===!0?F.id:0,Y=q[P];if(Y!==void 0){for(const Q in Y){const K=Y[Q];for(const ne in K)H(K[ne].object),delete K[ne];delete Y[Q]}delete q[P],Object.keys(q).length===0&&delete i[G]}}}function _(){D(),d=!0,o!==l&&(o=l,T(o.object))}function D(){l.geometry=null,l.program=null,l.wireframe=!1}return{setup:g,reset:_,resetDefaultState:D,dispose:S,releaseStatesOfGeometry:m,releaseStatesOfObject:c,releaseStatesOfProgram:w,initAttributes:W,enableAttribute:f,disableUnusedAttributes:L}}function rc(e,n,t){let i;function l(R){i=R}function o(R,T){e.drawArrays(i,R,T),t.update(T,i,1)}function d(R,T,H){H!==0&&(e.drawArraysInstanced(i,R,T,H),t.update(T,i,H))}function g(R,T,H){if(H===0)return;n.get("WEBGL_multi_draw").multiDrawArraysWEBGL(i,R,0,T,0,H);let p=0;for(let M=0;M<H;M++)p+=T[M];t.update(p,i,1)}this.setMode=l,this.render=o,this.renderInstances=d,this.renderMultiDraw=g}function ac(e,n,t,i){let l;function o(){if(l!==void 0)return l;if(n.has("EXT_texture_filter_anisotropic")===!0){const w=n.get("EXT_texture_filter_anisotropic");l=e.getParameter(w.MAX_TEXTURE_MAX_ANISOTROPY_EXT)}else l=0;return l}function d(w){return!(w!==Ut&&i.convert(w)!==e.getParameter(e.IMPLEMENTATION_COLOR_READ_FORMAT))}function g(w){const c=w===Dt&&(n.has("EXT_color_buffer_half_float")||n.has("EXT_color_buffer_float"));return!(w!==Ct&&w!==Bt&&!c&&i.convert(w)!==e.getParameter(e.IMPLEMENTATION_COLOR_READ_TYPE))}function R(w){if(w==="highp"){if(e.getShaderPrecisionFormat(e.VERTEX_SHADER,e.HIGH_FLOAT).precision>0&&e.getShaderPrecisionFormat(e.FRAGMENT_SHADER,e.HIGH_FLOAT).precision>0)return"highp";w="mediump"}return w==="mediump"&&e.getShaderPrecisionFormat(e.VERTEX_SHADER,e.MEDIUM_FLOAT).precision>0&&e.getShaderPrecisionFormat(e.FRAGMENT_SHADER,e.MEDIUM_FLOAT).precision>0?"mediump":"lowp"}let T=t.precision!==void 0?t.precision:"highp";const H=R(T);H!==T&&(We("WebGLRenderer:",T,"not supported, using",H,"instead."),T=H);const I=t.logarithmicDepthBuffer===!0,p=t.reversedDepthBuffer===!0&&n.has("EXT_clip_control");t.reversedDepthBuffer===!0&&p===!1&&We("WebGLRenderer: Unable to use reversed depth buffer due to missing EXT_clip_control extension. Fallback to default depth buffer.");const M=e.getParameter(e.MAX_TEXTURE_IMAGE_UNITS),N=e.getParameter(e.MAX_VERTEX_TEXTURE_IMAGE_UNITS),W=e.getParameter(e.MAX_TEXTURE_SIZE),f=e.getParameter(e.MAX_CUBE_MAP_TEXTURE_SIZE),s=e.getParameter(e.MAX_VERTEX_ATTRIBS),L=e.getParameter(e.MAX_VERTEX_UNIFORM_VECTORS),z=e.getParameter(e.MAX_VARYING_VECTORS),h=e.getParameter(e.MAX_FRAGMENT_UNIFORM_VECTORS),S=e.getParameter(e.MAX_SAMPLES),m=e.getParameter(e.SAMPLES);return{isWebGL2:!0,getMaxAnisotropy:o,getMaxPrecision:R,textureFormatReadable:d,textureTypeReadable:g,precision:T,logarithmicDepthBuffer:I,reversedDepthBuffer:p,maxTextures:M,maxVertexTextures:N,maxTextureSize:W,maxCubemapSize:f,maxAttributes:s,maxVertexUniforms:L,maxVaryings:z,maxFragmentUniforms:h,maxSamples:S,samples:m}}function oc(e){const n=this;let t=null,i=0,l=!1,o=!1;const d=new Ga,g=new Fe,R={value:null,needsUpdate:!1};this.uniform=R,this.numPlanes=0,this.numIntersection=0,this.init=function(I,p){const M=I.length!==0||p||i!==0||l;return l=p,i=I.length,M},this.beginShadows=function(){o=!0,H(null)},this.endShadows=function(){o=!1},this.setGlobalState=function(I,p){t=H(I,p,0)},this.setState=function(I,p,M){const N=I.clippingPlanes,W=I.clipIntersection,f=I.clipShadows,s=e.get(I);if(!l||N===null||N.length===0||o&&!f)o?H(null):T();else{const L=o?0:i,z=L*4;let h=s.clippingState||null;R.value=h,h=H(N,p,z,M);for(let S=0;S!==z;++S)h[S]=t[S];s.clippingState=h,this.numIntersection=W?this.numPlanes:0,this.numPlanes+=L}};function T(){R.value!==t&&(R.value=t,R.needsUpdate=i>0),n.numPlanes=i,n.numIntersection=0}function H(I,p,M,N){const W=I!==null?I.length:0;let f=null;if(W!==0){if(f=R.value,N!==!0||f===null){const s=M+W*4,L=p.matrixWorldInverse;g.getNormalMatrix(L),(f===null||f.length<s)&&(f=new Float32Array(s));for(let z=0,h=M;z!==W;++z,h+=4)d.copy(I[z]).applyMatrix4(L,g),d.normal.toArray(f,h),f[h+3]=d.constant}R.value=f,R.needsUpdate=!0}return n.numPlanes=W,n.numIntersection=0,f}}const Zt=4,sc=6,lc=20,cc=256,nn=new gr,qi=new et;let yn=null,Fn=0,On=0,Bn=!1;const fc=new Ne,Ht=new Ne;class Zi{constructor(n){this._renderer=n,this._pingPongRenderTarget=null,this._lodMax=0,this._cubeSize=0,this._sizeLods=[],this._lodMeshes=[],this._backgroundBox=null,this._cubemapMaterial=null,this._equirectMaterial=null,this._blurMaterial=null,this._ggxMaterial=null}fromScene(n,t=0,i=.1,l=100,o={}){const{size:d=256,position:g=fc}=o;yn=this._renderer.getRenderTarget(),Fn=this._renderer.getActiveCubeFace(),On=this._renderer.getActiveMipmapLevel(),Bn=this._renderer.xr.enabled,this._renderer.xr.enabled=!1,this._setSize(d);const R=this._allocateTargets();return R.depthBuffer=!0,this._sceneToCubeUV(n,i,l,R,g),t>0&&this._blur(R,0,0,t),this._applyPMREM(R),this._cleanup(R),R}fromEquirectangular(n,t=null){return this._fromTexture(n,t)}fromCubemap(n,t=null){return this._fromTexture(n,t)}compileCubemapShader(){this._cubemapMaterial===null&&(this._cubemapMaterial=Ji(),this._compileMaterial(this._cubemapMaterial))}compileEquirectangularShader(){this._equirectMaterial===null&&(this._equirectMaterial=Qi(),this._compileMaterial(this._equirectMaterial))}dispose(){this._dispose(),this._cubemapMaterial!==null&&this._cubemapMaterial.dispose(),this._equirectMaterial!==null&&this._equirectMaterial.dispose(),this._backgroundBox!==null&&(this._backgroundBox.geometry.dispose(),this._backgroundBox.material.dispose())}_setSize(n){this._lodMax=Math.floor(Math.log2(n)),this._cubeSize=Math.pow(2,this._lodMax)}_dispose(){this._blurMaterial!==null&&this._blurMaterial.dispose(),this._ggxMaterial!==null&&this._ggxMaterial.dispose(),this._pingPongRenderTarget!==null&&this._pingPongRenderTarget.dispose();for(let n=0;n<this._lodMeshes.length;n++)this._lodMeshes[n].geometry.dispose()}_cleanup(n){this._renderer.setRenderTarget(yn,Fn,On),this._renderer.xr.enabled=Bn,n.scissorTest=!1,Xt(n,0,0,n.width,n.height)}_fromTexture(n,t){n.mapping===cn||n.mapping===jt?this._setSize(n.image.length===0?16:n.image[0].width||n.image[0].image.width):this._setSize(n.image.width/4),yn=this._renderer.getRenderTarget(),Fn=this._renderer.getActiveCubeFace(),On=this._renderer.getActiveMipmapLevel(),Bn=this._renderer.xr.enabled,this._renderer.xr.enabled=!1;const i=t||this._allocateTargets();return this._textureToCubeUV(n,i),this._applyPMREM(i),this._cleanup(i),i}_allocateTargets(){const n=3*Math.max(this._cubeSize,112),t=4*this._cubeSize,i={magFilter:vt,minFilter:vt,generateMipmaps:!1,type:Dt,format:Ut,colorSpace:Or,depthBuffer:!1},l=$i(n,t,i);if(this._pingPongRenderTarget===null||this._pingPongRenderTarget.width!==n||this._pingPongRenderTarget.height!==t){this._pingPongRenderTarget!==null&&this._dispose(),this._pingPongRenderTarget=$i(n,t,i);const{_lodMax:o}=this;({lodMeshes:this._lodMeshes,sizeLods:this._sizeLods}=dc(o)),this._blurMaterial=pc(o,n,t),this._ggxMaterial=uc(o,n,t)}return l}_compileMaterial(n){const t=new Nt(new xn,n);this._renderer.compile(t,nn)}_sceneToCubeUV(n,t,i,l,o){const R=new _n(90,1,t,i),T=[1,-1,1,1,1,1],H=[1,1,1,-1,-1,-1],I=this._renderer,p=I.autoClear,M=I.toneMapping;I.getClearColor(qi),I.toneMapping=Pt,I.autoClear=!1,I.state.buffers.depth.getReversed()&&(I.setRenderTarget(l),I.clearDepth(),I.setRenderTarget(null)),this._backgroundBox===null&&(this._backgroundBox=new Nt(new $n,new co({name:"PMREM.Background",side:St,depthWrite:!1,depthTest:!1})));const W=this._backgroundBox,f=W.material;let s=!1;const L=n.background;L?L.isColor&&(f.color.copy(L),n.background=null,s=!0):(f.color.copy(qi),s=!0);for(let z=0;z<6;z++){const h=z%3;h===0?(R.up.set(0,T[z],0),R.position.set(o.x,o.y,o.z),R.lookAt(o.x+H[z],o.y,o.z)):h===1?(R.up.set(0,0,T[z]),R.position.set(o.x,o.y,o.z),R.lookAt(o.x,o.y+H[z],o.z)):(R.up.set(0,T[z],0),R.position.set(o.x,o.y,o.z),R.lookAt(o.x,o.y,o.z+H[z]));const S=this._cubeSize;Xt(l,h*S,z>2?S:0,S,S),I.setRenderTarget(l),s&&I.render(W,R),I.render(n,R)}I.toneMapping=M,I.autoClear=p,n.background=L}_textureToCubeUV(n,t){const i=this._renderer,l=n.mapping===cn||n.mapping===jt;l?(this._cubemapMaterial===null&&(this._cubemapMaterial=Ji()),this._cubemapMaterial.uniforms.flipEnvMap.value=n.isRenderTargetTexture===!1?-1:1):this._equirectMaterial===null&&(this._equirectMaterial=Qi());const o=l?this._cubemapMaterial:this._equirectMaterial,d=this._lodMeshes[0];d.material=o;const g=o.uniforms;g.envMap.value=n;const R=this._cubeSize;Xt(t,0,0,3*R,2*R),i.setRenderTarget(t),i.render(d,nn)}_applyPMREM(n){const t=this._renderer,i=t.autoClear;t.autoClear=!1;const l=this._lodMeshes.length;for(let o=1;o<l;o++)this._applyGGXFilter(n,o-1,o);t.autoClear=i}_applyGGXFilter(n,t,i){const l=this._renderer,o=this._pingPongRenderTarget,d=this._ggxMaterial,g=this._lodMeshes[i];g.material=d;const R=d.uniforms,T=i/(this._lodMeshes.length-1),H=t/(this._lodMeshes.length-1),I=Math.sqrt(T*T-H*H),p=T*1.25,M=I*p,{_lodMax:N}=this,W=this._sizeLods[i],f=3*W*(i>N-Zt?i-N+Zt:0),s=4*(this._cubeSize-W);R.envMap.value=n.texture,R.roughness.value=M,R.mipInt.value=N-t,Xt(o,f,s,3*W,2*W),l.setRenderTarget(o),l.render(g,nn),R.envMap.value=o.texture,R.roughness.value=0,R.mipInt.value=N-i,Xt(n,f,s,3*W,2*W),l.setRenderTarget(n),l.render(g,nn)}_blur(n,t,i,l){const o=this._pingPongRenderTarget,d=Math.min(l,Math.PI)/Math.SQRT2;this._blurPass(n,o,t,i,d),this._blurPass(o,n,i,i,d)}_blurPass(n,t,i,l,o){const d=this._renderer,g=this._blurMaterial,R=this._lodMeshes[l];R.material=g;const T=g.uniforms;T.envMap.value=n.texture,T.sigma.value=o,T.mipInt.value=this._lodMax-i;const H=this._sizeLods[l],I=3*H*(l>this._lodMax-Zt?l-this._lodMax+Zt:0),p=4*(this._cubeSize-H);Xt(t,I,p,3*H,2*H),d.setRenderTarget(t),d.render(R,nn)}}function dc(e){const n=[],t=[];let i=e;const l=e-Zt+1+sc;for(let o=0;o<l;o++){const d=Math.pow(2,i);n.push(d);const g=1/(d-2),R=-g,T=1+g,H=[R,R,T,R,T,T,R,R,T,T,R,T],I=6,p=6,M=3,N=new Float32Array(M*p*I),W=new Float32Array(M*p*I);for(let s=0;s<I;s++){const L=s%3*2/3-1,z=s>2?0:-1,h=[L,z,0,L+2/3,z,0,L+2/3,z+1,0,L,z,0,L+2/3,z+1,0,L,z+1,0];N.set(h,M*p*s);for(let S=0;S<p;S++){const m=H[S*2]*2-1,w=H[S*2+1]*2-1;s===0?Ht.set(1,w,m):s===1?Ht.set(-m,1,-w):s===2?Ht.set(-m,w,1):s===3?Ht.set(-1,w,-m):s===4?Ht.set(-m,-1,w):Ht.set(m,w,-1),Ht.toArray(W,(s*p+S)*M)}}const f=new xn;f.setAttribute("position",new Wn(N,M)),f.setAttribute("outputDirection",new Wn(W,M)),t.push(new Nt(f,null)),i>Zt&&i--}return{lodMeshes:t,sizeLods:n}}function $i(e,n,t){const i=new Mt(e,n,t);return i.texture.mapping=Mn,i.texture.name="PMREM.cubeUv",i.scissorTest=!0,i}function Xt(e,n,t,i,l){e.viewport.set(n,t,i,l),e.scissor.set(n,t,i,l)}function uc(e,n,t){return new It({name:"PMREMGGXConvolution",defines:{GGX_SAMPLES:cc,CUBEUV_TEXEL_WIDTH:1/n,CUBEUV_TEXEL_HEIGHT:1/t,CUBEUV_MAX_MIP:`${e}.0`},uniforms:{envMap:{value:null},roughness:{value:0},mipInt:{value:0}},vertexShader:Tn(),fragmentShader:`

			precision highp float;
			precision highp int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform float roughness;
			uniform float mipInt;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			#define PI 3.14159265359

			// Van der Corput radical inverse
			float radicalInverse_VdC(uint bits) {
				bits = (bits << 16u) | (bits >> 16u);
				bits = ((bits & 0x55555555u) << 1u) | ((bits & 0xAAAAAAAAu) >> 1u);
				bits = ((bits & 0x33333333u) << 2u) | ((bits & 0xCCCCCCCCu) >> 2u);
				bits = ((bits & 0x0F0F0F0Fu) << 4u) | ((bits & 0xF0F0F0F0u) >> 4u);
				bits = ((bits & 0x00FF00FFu) << 8u) | ((bits & 0xFF00FF00u) >> 8u);
				return float(bits) * 2.3283064365386963e-10; // / 0x100000000
			}

			// Hammersley sequence
			vec2 hammersley(uint i, uint N) {
				return vec2(float(i) / float(N), radicalInverse_VdC(i));
			}

			// GGX VNDF importance sampling (Eric Heitz 2018)
			// "Sampling the GGX Distribution of Visible Normals"
			// https://jcgt.org/published/0007/04/01/
			vec3 importanceSampleGGX_VNDF(vec2 Xi, vec3 V, float roughness) {
				float alpha = roughness * roughness;

				// Section 4.1: Orthonormal basis
				vec3 T1 = vec3(1.0, 0.0, 0.0);
				vec3 T2 = cross(V, T1);

				// Section 4.2: Parameterization of projected area
				float r = sqrt(Xi.x);
				float phi = 2.0 * PI * Xi.y;
				float t1 = r * cos(phi);
				float t2 = r * sin(phi);
				float s = 0.5 * (1.0 + V.z);
				t2 = (1.0 - s) * sqrt(1.0 - t1 * t1) + s * t2;

				// Section 4.3: Reprojection onto hemisphere
				vec3 Nh = t1 * T1 + t2 * T2 + sqrt(max(0.0, 1.0 - t1 * t1 - t2 * t2)) * V;

				// Section 3.4: Transform back to ellipsoid configuration
				return normalize(vec3(alpha * Nh.x, alpha * Nh.y, max(0.0, Nh.z)));
			}

			void main() {
				vec3 N = normalize(vOutputDirection);
				vec3 V = N; // Assume view direction equals normal for pre-filtering

				vec3 prefilteredColor = vec3(0.0);
				float totalWeight = 0.0;

				// For very low roughness, just sample the environment directly
				if (roughness < 0.001) {
					gl_FragColor = vec4(bilinearCubeUV(envMap, N, mipInt), 1.0);
					return;
				}

				// Tangent space basis for VNDF sampling
				vec3 up = abs(N.z) < 0.999 ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
				vec3 tangent = normalize(cross(up, N));
				vec3 bitangent = cross(N, tangent);

				for(uint i = 0u; i < uint(GGX_SAMPLES); i++) {
					vec2 Xi = hammersley(i, uint(GGX_SAMPLES));

					// For PMREM, V = N, so in tangent space V is always (0, 0, 1)
					vec3 H_tangent = importanceSampleGGX_VNDF(Xi, vec3(0.0, 0.0, 1.0), roughness);

					// Transform H back to world space
					vec3 H = normalize(tangent * H_tangent.x + bitangent * H_tangent.y + N * H_tangent.z);
					vec3 L = normalize(2.0 * dot(V, H) * H - V);

					float NdotL = max(dot(N, L), 0.0);

					if(NdotL > 0.0) {
						// Sample environment at fixed mip level
						// VNDF importance sampling handles the distribution filtering
						vec3 sampleColor = bilinearCubeUV(envMap, L, mipInt);

						// Weight by NdotL for the split-sum approximation
						// VNDF PDF naturally accounts for the visible microfacet distribution
						prefilteredColor += sampleColor * NdotL;
						totalWeight += NdotL;
					}
				}

				if (totalWeight > 0.0) {
					prefilteredColor = prefilteredColor / totalWeight;
				}

				gl_FragColor = vec4(prefilteredColor, 1.0);
			}
		`,blending:wt,depthTest:!1,depthWrite:!1})}function pc(e,n,t){return new It({name:"SphericalGaussianBlur",defines:{SAMPLES:lc,CUBEUV_TEXEL_WIDTH:1/n,CUBEUV_TEXEL_HEIGHT:1/t,CUBEUV_MAX_MIP:`${e}.0`},uniforms:{envMap:{value:null},sigma:{value:0},mipInt:{value:0}},vertexShader:Tn(),fragmentShader:`

			precision highp float;
			precision highp int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;
			uniform float sigma;
			uniform float mipInt;

			#define ENVMAP_TYPE_CUBE_UV
			#include <cube_uv_reflection_fragment>

			#define PI 3.14159265359
			#define GOLDEN_ANGLE 2.39996322973

			void main() {

				if ( sigma == 0.0 ) {

					gl_FragColor = vec4( bilinearCubeUV( envMap, vOutputDirection, mipInt ), 1.0 );
					return;

				}

				vec3 outputDirection = normalize( vOutputDirection );

				vec3 up = abs( outputDirection.z ) < 0.999 ? vec3( 0.0, 0.0, 1.0 ) : vec3( 1.0, 0.0, 0.0 );
				vec3 tangent = normalize( cross( up, outputDirection ) );
				vec3 bitangent = cross( outputDirection, tangent );

				// Truncate the kernel at three standard deviations or at the antipode.
				float thetaMax = min( 3.0 * sigma, PI );
				float truncation = 1.0 - exp( - 0.5 * thetaMax * thetaMax / ( sigma * sigma ) );

				vec3 accumColor = vec3( 0.0 );
				float accumWeight = 0.0;

				for ( int i = 0; i < SAMPLES; i ++ ) {

					// Stratified inverse-CDF sampling of the Gaussian, placed on a golden-angle spiral.
					float stratum = ( float( i ) + 0.5 ) / float( SAMPLES );
					float theta = sigma * sqrt( - 2.0 * log( 1.0 - stratum * truncation ) );
					float phi = float( i ) * GOLDEN_ANGLE;

					vec3 offset = cos( phi ) * tangent + sin( phi ) * bitangent;
					vec3 sampleDirection = cos( theta ) * outputDirection + sin( theta ) * offset;

					// Correct the planar sample density to solid angle.
					float weight = sin( theta ) / theta;

					accumColor += weight * bilinearCubeUV( envMap, sampleDirection, mipInt );
					accumWeight += weight;

				}

				gl_FragColor = vec4( accumColor / accumWeight, 1.0 );

			}
		`,blending:wt,depthTest:!1,depthWrite:!1})}function Qi(){return new It({name:"EquirectangularToCubeUV",uniforms:{envMap:{value:null}},vertexShader:Tn(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			varying vec3 vOutputDirection;

			uniform sampler2D envMap;

			#include <common>

			void main() {

				vec3 outputDirection = normalize( vOutputDirection );
				vec2 uv = equirectUv( outputDirection );

				gl_FragColor = vec4( texture2D ( envMap, uv ).rgb, 1.0 );

			}
		`,blending:wt,depthTest:!1,depthWrite:!1})}function Ji(){return new It({name:"CubemapToCubeUV",uniforms:{envMap:{value:null},flipEnvMap:{value:-1}},vertexShader:Tn(),fragmentShader:`

			precision mediump float;
			precision mediump int;

			uniform float flipEnvMap;

			varying vec3 vOutputDirection;

			uniform samplerCube envMap;

			void main() {

				gl_FragColor = textureCube( envMap, vec3( flipEnvMap * vOutputDirection.x, vOutputDirection.yz ) );

			}
		`,blending:wt,depthTest:!1,depthWrite:!1})}function Tn(){return`

		precision mediump float;
		precision mediump int;

		attribute vec3 outputDirection;

		varying vec3 vOutputDirection;

		void main() {

			vOutputDirection = outputDirection;
			gl_Position = vec4( position, 1.0 );

		}
	`}class Hr extends Mt{constructor(n=1,t={}){super(n,n,t),this.isWebGLCubeRenderTarget=!0;const i={width:n,height:n,depth:1},l=[i,i,i,i,i,i];this.texture=new Rr(l),this._setTextureOptions(t),this.texture.isRenderTargetTexture=!0}fromEquirectangularTexture(n,t){this.texture.type=t.type,this.texture.colorSpace=t.colorSpace,this.texture.generateMipmaps=t.generateMipmaps,this.texture.minFilter=t.minFilter,this.texture.magFilter=t.magFilter;const i={uniforms:{tEquirect:{value:null}},vertexShader:`

				varying vec3 vWorldDirection;

				vec3 transformDirection( in vec3 dir, in mat4 matrix ) {

					return normalize( ( matrix * vec4( dir, 0.0 ) ).xyz );

				}

				void main() {

					vWorldDirection = transformDirection( position, modelMatrix );

					#include <begin_vertex>
					#include <project_vertex>

				}
			`,fragmentShader:`

				uniform sampler2D tEquirect;

				varying vec3 vWorldDirection;

				#include <common>

				void main() {

					vec3 direction = normalize( vWorldDirection );

					vec2 sampleUV = equirectUv( direction );

					gl_FragColor = texture2D( tEquirect, sampleUV );

				}
			`},l=new $n(5,5,5),o=new It({name:"CubemapFromEquirect",uniforms:kn(i.uniforms),vertexShader:i.vertexShader,fragmentShader:i.fragmentShader,side:St,blending:wt});o.uniforms.tEquirect.value=t;const d=new Nt(l,o),g=t.minFilter;return t.minFilter===Kt&&(t.minFilter=vt),new Ja(1,10,this).update(n,d),t.minFilter=g,d.geometry.dispose(),d.material.dispose(),this}clear(n,t=!0,i=!0,l=!0){const o=n.getRenderTarget();for(let d=0;d<6;d++)n.setRenderTarget(this,d),n.clear(t,i,l);n.setRenderTarget(o)}}function hc(e){let n=new WeakMap,t=new WeakMap,i=null;function l(p,M=!1){return p==null?null:M?d(p):o(p)}function o(p){if(p&&p.isTexture){const M=p.mapping;if(M===In||M===Nn)if(n.has(p)){const N=n.get(p).texture;return g(N,p.mapping)}else{const N=p.image;if(N&&N.height>0){const W=new Hr(N.height);return W.fromEquirectangularTexture(e,p),n.set(p,W),p.addEventListener("dispose",T),g(W.texture,p.mapping)}else return null}}return p}function d(p){if(p&&p.isTexture){const M=p.mapping,N=M===In||M===Nn,W=M===cn||M===jt;if(N||W){let f=t.get(p);const s=f!==void 0?f.texture.pmremVersion:0;if(p.isRenderTargetTexture&&p.pmremVersion!==s)return i===null&&(i=new Zi(e)),f=N?i.fromEquirectangular(p,f):i.fromCubemap(p,f),f.texture.pmremVersion=p.pmremVersion,t.set(p,f),f.texture;if(f!==void 0)return f.texture;{const L=p.image;return N&&L&&L.height>0||W&&L&&R(L)?(i===null&&(i=new Zi(e)),f=N?i.fromEquirectangular(p):i.fromCubemap(p),f.texture.pmremVersion=p.pmremVersion,t.set(p,f),p.addEventListener("dispose",H),f.texture):null}}}return p}function g(p,M){return M===In?p.mapping=cn:M===Nn&&(p.mapping=jt),p}function R(p){let M=0;const N=6;for(let W=0;W<N;W++)p[W]!==void 0&&M++;return M===N}function T(p){const M=p.target;M.removeEventListener("dispose",T);const N=n.get(M);N!==void 0&&(n.delete(M),N.dispose())}function H(p){const M=p.target;M.removeEventListener("dispose",H);const N=t.get(M);N!==void 0&&(t.delete(M),N.dispose())}function I(){n=new WeakMap,t=new WeakMap,i!==null&&(i.dispose(),i=null)}return{get:l,dispose:I}}function mc(e){const n={};function t(i){if(n[i]!==void 0)return n[i];const l=e.getExtension(i);return n[i]=l,l}return{has:function(i){return t(i)!==null},init:function(){t("EXT_color_buffer_float"),t("WEBGL_clip_cull_distance"),t("OES_texture_float_linear"),t("EXT_color_buffer_half_float"),t("WEBGL_multisampled_render_to_texture"),t("WEBGL_render_shared_exponent")},get:function(i){const l=t(i);return l===null&&Ba("WebGLRenderer: "+i+" extension not supported."),l}}}function _c(e,n,t,i){const l={},o=new WeakMap;function d(I){const p=I.target;p.index!==null&&n.remove(p.index);for(const N in p.attributes)n.remove(p.attributes[N]);p.removeEventListener("dispose",d),delete l[p.id];const M=o.get(p);M&&(n.remove(M),o.delete(p)),i.releaseStatesOfGeometry(p),p.isInstancedBufferGeometry===!0&&delete p._maxInstanceCount,t.memory.geometries--}function g(I,p){return l[p.id]===!0||(p.addEventListener("dispose",d),l[p.id]=!0,t.memory.geometries++),p}function R(I){const p=I.attributes;for(const M in p)n.update(p[M],e.ARRAY_BUFFER)}function T(I){const p=[],M=I.index,N=I.attributes.position;let W=0;if(N===void 0)return;if(M!==null){const L=M.array;W=M.version;for(let z=0,h=L.length;z<h;z+=3){const S=L[z+0],m=L[z+1],w=L[z+2];p.push(S,m,m,w,w,S)}}else{const L=N.array;W=N.version;for(let z=0,h=L.length/3-1;z<h;z+=3){const S=z+0,m=z+1,w=z+2;p.push(S,m,m,w,w,S)}}const f=new(N.count>=65535?so:lo)(p,1);f.version=W;const s=o.get(I);s&&n.remove(s),o.set(I,f)}function H(I){const p=o.get(I);if(p){const M=I.index;M!==null&&p.version<M.version&&T(I)}else T(I);return o.get(I)}return{get:g,update:R,getWireframeAttribute:H}}function gc(e,n,t){let i;function l(I){i=I}let o,d;function g(I){o=I.type,d=I.bytesPerElement}function R(I,p){e.drawElements(i,p,o,I*d),t.update(p,i,1)}function T(I,p,M){M!==0&&(e.drawElementsInstanced(i,p,o,I*d,M),t.update(p,i,M))}function H(I,p,M){if(M===0)return;n.get("WEBGL_multi_draw").multiDrawElementsWEBGL(i,p,0,o,I,0,M);let W=0;for(let f=0;f<M;f++)W+=p[f];t.update(W,i,1)}this.setMode=l,this.setIndex=g,this.render=R,this.renderInstances=T,this.renderMultiDraw=H}function vc(e){const n={geometries:0,textures:0},t={frame:0,calls:0,triangles:0,points:0,lines:0};function i(o,d,g){switch(t.calls++,d){case e.TRIANGLES:t.triangles+=g*(o/3);break;case e.LINES:t.lines+=g*(o/2);break;case e.LINE_STRIP:t.lines+=g*(o-1);break;case e.LINE_LOOP:t.lines+=g*o;break;case e.POINTS:t.points+=g*o;break;default:Je("WebGLInfo: Unknown draw mode:",d);break}}function l(){t.calls=0,t.triangles=0,t.points=0,t.lines=0}return{memory:n,render:t,programs:null,autoReset:!0,reset:l,update:i}}function Sc(e,n,t){const i=new WeakMap,l=new _t;function o(d,g,R){const T=d.morphTargetInfluences,H=g.morphAttributes.position||g.morphAttributes.normal||g.morphAttributes.color,I=H!==void 0?H.length:0;let p=i.get(g);if(p===void 0||p.count!==I){let _=function(){w.dispose(),i.delete(g),g.removeEventListener("dispose",_)};p!==void 0&&p.texture.dispose();const M=g.morphAttributes.position!==void 0,N=g.morphAttributes.normal!==void 0,W=g.morphAttributes.color!==void 0,f=g.morphAttributes.position||[],s=g.morphAttributes.normal||[],L=g.morphAttributes.color||[];let z=0;M===!0&&(z=1),N===!0&&(z=2),W===!0&&(z=3);let h=g.attributes.position.count*z,S=1;h>n.maxTextureSize&&(S=Math.ceil(h/n.maxTextureSize),h=n.maxTextureSize);const m=new Float32Array(h*S*4*I),w=new Pr(m,h,S,I);w.type=Bt,w.needsUpdate=!0;const c=z*4;for(let D=0;D<I;D++){const F=f[D],G=s[D],q=L[D],P=h*S*4*D;for(let Y=0;Y<F.count;Y++){const Q=Y*c;M===!0&&(l.fromBufferAttribute(F,Y),m[P+Q+0]=l.x,m[P+Q+1]=l.y,m[P+Q+2]=l.z,m[P+Q+3]=0),N===!0&&(l.fromBufferAttribute(G,Y),m[P+Q+4]=l.x,m[P+Q+5]=l.y,m[P+Q+6]=l.z,m[P+Q+7]=0),W===!0&&(l.fromBufferAttribute(q,Y),m[P+Q+8]=l.x,m[P+Q+9]=l.y,m[P+Q+10]=l.z,m[P+Q+11]=q.itemSize===4?l.w:1)}}p={count:I,texture:w,size:new gt(h,S)},i.set(g,p),g.addEventListener("dispose",_)}if(d.isInstancedMesh===!0&&d.morphTexture!==null)R.getUniforms().setValue(e,"morphTexture",d.morphTexture,t);else{let M=0;for(let W=0;W<T.length;W++)M+=T[W];const N=g.morphTargetsRelative?1:1-M;R.getUniforms().setValue(e,"morphTargetBaseInfluence",N),R.getUniforms().setValue(e,"morphTargetInfluences",T)}R.getUniforms().setValue(e,"morphTargetsTexture",p.texture,t),R.getUniforms().setValue(e,"morphTargetsTextureSize",p.size)}return{update:o}}function Ec(e,n,t,i,l){let o=new WeakMap;function d(T){const H=l.render.frame,I=T.geometry,p=n.get(T,I);if(o.get(p)!==H&&(n.update(p),o.set(p,H)),T.isInstancedMesh&&(T.hasEventListener("dispose",R)===!1&&T.addEventListener("dispose",R),o.get(T)!==H&&(t.update(T.instanceMatrix,e.ARRAY_BUFFER),T.instanceColor!==null&&t.update(T.instanceColor,e.ARRAY_BUFFER),o.set(T,H))),T.isSkinnedMesh){const M=T.skeleton;o.get(M)!==H&&(M.update(),o.set(M,H))}return p}function g(){o=new WeakMap}function R(T){const H=T.target;H.removeEventListener("dispose",R),i.releaseStatesOfObject(H),t.remove(H.instanceMatrix),H.instanceColor!==null&&t.remove(H.instanceColor)}return{update:d,dispose:g}}const xc={[Fr]:"LINEAR_TONE_MAPPING",[yr]:"REINHARD_TONE_MAPPING",[Nr]:"CINEON_TONE_MAPPING",[Ir]:"ACES_FILMIC_TONE_MAPPING",[Dr]:"AGX_TONE_MAPPING",[wr]:"NEUTRAL_TONE_MAPPING",[Ur]:"CUSTOM_TONE_MAPPING"};function Mc(e,n,t,i,l,o){const d=new Mt(n,t,{type:e,depthBuffer:l,stencilBuffer:o,samples:i?4:0,storeMultisampledDepthBuffer:!1,storeMultisampledStencilBuffer:!1,resolveDepthBuffer:!1,resolveStencilBuffer:!1});let g=null,R=null;const T=new xn;T.setAttribute("position",new fi([-1,3,0,-1,-1,0,3,-1,0],3)),T.setAttribute("uv",new fi([0,2,0,0,2,0],2));const H=new Ia({uniforms:{tDiffuse:{value:null}},vertexShader:`
			precision highp float;

			uniform mat4 modelViewMatrix;
			uniform mat4 projectionMatrix;

			attribute vec3 position;
			attribute vec2 uv;

			varying vec2 vUv;

			void main() {
				vUv = uv;
				gl_Position = projectionMatrix * modelViewMatrix * vec4( position, 1.0 );
			}`,fragmentShader:`
			precision highp float;

			uniform sampler2D tDiffuse;

			varying vec2 vUv;

			#include <tonemapping_pars_fragment>
			#include <colorspace_pars_fragment>

			void main() {
				gl_FragColor = texture2D( tDiffuse, vUv );

				#ifdef LINEAR_TONE_MAPPING
					gl_FragColor.rgb = LinearToneMapping( gl_FragColor.rgb );
				#elif defined( REINHARD_TONE_MAPPING )
					gl_FragColor.rgb = ReinhardToneMapping( gl_FragColor.rgb );
				#elif defined( CINEON_TONE_MAPPING )
					gl_FragColor.rgb = CineonToneMapping( gl_FragColor.rgb );
				#elif defined( ACES_FILMIC_TONE_MAPPING )
					gl_FragColor.rgb = ACESFilmicToneMapping( gl_FragColor.rgb );
				#elif defined( AGX_TONE_MAPPING )
					gl_FragColor.rgb = AgXToneMapping( gl_FragColor.rgb );
				#elif defined( NEUTRAL_TONE_MAPPING )
					gl_FragColor.rgb = NeutralToneMapping( gl_FragColor.rgb );
				#elif defined( CUSTOM_TONE_MAPPING )
					gl_FragColor.rgb = CustomToneMapping( gl_FragColor.rgb );
				#endif

				#ifdef SRGB_TRANSFER
					gl_FragColor = sRGBTransferOETF( gl_FragColor );
				#endif
			}`,depthTest:!1,depthWrite:!1}),I=new Nt(T,H),p=new gr(-1,1,1,-1,0,1);let M=null,N=null,W=!1,f,s=null,L=[],z=!1;this.setSize=function(h,S){d.setSize(h,S),g!==null&&g.setSize(h,S),R!==null&&R.setSize(h,S);for(let m=0;m<L.length;m++){const w=L[m];w.setSize&&w.setSize(h,S)}},this.setEffects=function(h){L=h,z=L.length>0&&L[0].isRenderPass===!0;const S=d.width,m=d.height;L.length>0&&g===null&&(g=new Mt(S,m,{type:Dt,depthBuffer:!1,stencilBuffer:!1}),R=new Mt(S,m,{type:Dt,depthBuffer:!1,stencilBuffer:!1}));for(let w=0;w<L.length;w++){const c=L[w];c.setSize&&c.setSize(S,m)}},this.begin=function(h,S){if(W||h.toneMapping===Pt&&L.length===0)return!1;if(s=S,S!==null){const m=S.width,w=S.height;(d.width!==m||d.height!==w)&&this.setSize(m,w)}return z===!1&&h.setRenderTarget(d),f=h.toneMapping,h.toneMapping=Pt,!0},this.hasRenderPass=function(){return z},this.end=function(h,S){h.toneMapping=f,W=!0;let m=d,w=g;for(let c=0;c<L.length;c++){const _=L[c];_.enabled!==!1&&(_.render(h,w,m,S),_.needsSwap!==!1&&(m=w,w=w===g?R:g))}if(M!==h.outputColorSpace||N!==h.toneMapping){M=h.outputColorSpace,N=h.toneMapping,H.defines={},nt.getTransfer(M)===$e&&(H.defines.SRGB_TRANSFER="");const c=xc[N];c&&(H.defines[c]=""),H.needsUpdate=!0}H.uniforms.tDiffuse.value=m.texture,h.setRenderTarget(s),h.render(I,p),s=null,W=!1},this.isCompositing=function(){return W},this.dispose=function(){d.dispose(),g!==null&&g.dispose(),R!==null&&R.dispose(),T.dispose(),H.dispose()}}const Vr=new _o,Yn=new Sn(1,1),Wr=new Pr,kr=new mo,zr=new Rr,ji=[],er=[],tr=new Float32Array(16),nr=new Float32Array(9),ir=new Float32Array(4);function en(e,n,t){const i=e[0];if(i<=0||i>0)return e;const l=n*t;let o=ji[l];if(o===void 0&&(o=new Float32Array(l),ji[l]=o),n!==0){i.toArray(o,0);for(let d=1,g=0;d!==n;++d)g+=t,e[d].toArray(o,g)}return o}function lt(e,n){if(e.length!==n.length)return!1;for(let t=0,i=e.length;t<i;t++)if(e[t]!==n[t])return!1;return!0}function ct(e,n){for(let t=0,i=n.length;t<i;t++)e[t]=n[t]}function An(e,n){let t=er[n];t===void 0&&(t=new Int32Array(n),er[n]=t);for(let i=0;i!==n;++i)t[i]=e.allocateTextureUnit();return t}function Tc(e,n){const t=this.cache;t[0]!==n&&(e.uniform1f(this.addr,n),t[0]=n)}function Ac(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y)&&(e.uniform2f(this.addr,n.x,n.y),t[0]=n.x,t[1]=n.y);else{if(lt(t,n))return;e.uniform2fv(this.addr,n),ct(t,n)}}function Rc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z)&&(e.uniform3f(this.addr,n.x,n.y,n.z),t[0]=n.x,t[1]=n.y,t[2]=n.z);else if(n.r!==void 0)(t[0]!==n.r||t[1]!==n.g||t[2]!==n.b)&&(e.uniform3f(this.addr,n.r,n.g,n.b),t[0]=n.r,t[1]=n.g,t[2]=n.b);else{if(lt(t,n))return;e.uniform3fv(this.addr,n),ct(t,n)}}function bc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z||t[3]!==n.w)&&(e.uniform4f(this.addr,n.x,n.y,n.z,n.w),t[0]=n.x,t[1]=n.y,t[2]=n.z,t[3]=n.w);else{if(lt(t,n))return;e.uniform4fv(this.addr,n),ct(t,n)}}function Cc(e,n){const t=this.cache,i=n.elements;if(i===void 0){if(lt(t,n))return;e.uniformMatrix2fv(this.addr,!1,n),ct(t,n)}else{if(lt(t,i))return;ir.set(i),e.uniformMatrix2fv(this.addr,!1,ir),ct(t,i)}}function Pc(e,n){const t=this.cache,i=n.elements;if(i===void 0){if(lt(t,n))return;e.uniformMatrix3fv(this.addr,!1,n),ct(t,n)}else{if(lt(t,i))return;nr.set(i),e.uniformMatrix3fv(this.addr,!1,nr),ct(t,i)}}function Lc(e,n){const t=this.cache,i=n.elements;if(i===void 0){if(lt(t,n))return;e.uniformMatrix4fv(this.addr,!1,n),ct(t,n)}else{if(lt(t,i))return;tr.set(i),e.uniformMatrix4fv(this.addr,!1,tr),ct(t,i)}}function Uc(e,n){const t=this.cache;t[0]!==n&&(e.uniform1i(this.addr,n),t[0]=n)}function wc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y)&&(e.uniform2i(this.addr,n.x,n.y),t[0]=n.x,t[1]=n.y);else{if(lt(t,n))return;e.uniform2iv(this.addr,n),ct(t,n)}}function Dc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z)&&(e.uniform3i(this.addr,n.x,n.y,n.z),t[0]=n.x,t[1]=n.y,t[2]=n.z);else{if(lt(t,n))return;e.uniform3iv(this.addr,n),ct(t,n)}}function Ic(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z||t[3]!==n.w)&&(e.uniform4i(this.addr,n.x,n.y,n.z,n.w),t[0]=n.x,t[1]=n.y,t[2]=n.z,t[3]=n.w);else{if(lt(t,n))return;e.uniform4iv(this.addr,n),ct(t,n)}}function Nc(e,n){const t=this.cache;t[0]!==n&&(e.uniform1ui(this.addr,n),t[0]=n)}function yc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y)&&(e.uniform2ui(this.addr,n.x,n.y),t[0]=n.x,t[1]=n.y);else{if(lt(t,n))return;e.uniform2uiv(this.addr,n),ct(t,n)}}function Fc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z)&&(e.uniform3ui(this.addr,n.x,n.y,n.z),t[0]=n.x,t[1]=n.y,t[2]=n.z);else{if(lt(t,n))return;e.uniform3uiv(this.addr,n),ct(t,n)}}function Oc(e,n){const t=this.cache;if(n.x!==void 0)(t[0]!==n.x||t[1]!==n.y||t[2]!==n.z||t[3]!==n.w)&&(e.uniform4ui(this.addr,n.x,n.y,n.z,n.w),t[0]=n.x,t[1]=n.y,t[2]=n.z,t[3]=n.w);else{if(lt(t,n))return;e.uniform4uiv(this.addr,n),ct(t,n)}}function Bc(e,n,t){const i=this.cache,l=t.allocateTextureUnit();i[0]!==l&&(e.uniform1i(this.addr,l),i[0]=l);let o;this.type===e.SAMPLER_2D_SHADOW?(Yn.compareFunction=t.isReversedDepthBuffer()?qn:Zn,o=Yn):o=Vr,t.setTexture2D(n||o,l)}function Gc(e,n,t){const i=this.cache,l=t.allocateTextureUnit();i[0]!==l&&(e.uniform1i(this.addr,l),i[0]=l),t.setTexture3D(n||kr,l)}function Hc(e,n,t){const i=this.cache,l=t.allocateTextureUnit();i[0]!==l&&(e.uniform1i(this.addr,l),i[0]=l),t.setTextureCube(n||zr,l)}function Vc(e,n,t){const i=this.cache,l=t.allocateTextureUnit();i[0]!==l&&(e.uniform1i(this.addr,l),i[0]=l),t.setTexture2DArray(n||Wr,l)}function Wc(e){switch(e){case 5126:return Tc;case 35664:return Ac;case 35665:return Rc;case 35666:return bc;case 35674:return Cc;case 35675:return Pc;case 35676:return Lc;case 5124:case 35670:return Uc;case 35667:case 35671:return wc;case 35668:case 35672:return Dc;case 35669:case 35673:return Ic;case 5125:return Nc;case 36294:return yc;case 36295:return Fc;case 36296:return Oc;case 35678:case 36198:case 36298:case 36306:case 35682:return Bc;case 35679:case 36299:case 36307:return Gc;case 35680:case 36300:case 36308:case 36293:return Hc;case 36289:case 36303:case 36311:case 36292:return Vc}}function kc(e,n){e.uniform1fv(this.addr,n)}function zc(e,n){const t=en(n,this.size,2);e.uniform2fv(this.addr,t)}function Xc(e,n){const t=en(n,this.size,3);e.uniform3fv(this.addr,t)}function Yc(e,n){const t=en(n,this.size,4);e.uniform4fv(this.addr,t)}function Kc(e,n){const t=en(n,this.size,4);e.uniformMatrix2fv(this.addr,!1,t)}function qc(e,n){const t=en(n,this.size,9);e.uniformMatrix3fv(this.addr,!1,t)}function Zc(e,n){const t=en(n,this.size,16);e.uniformMatrix4fv(this.addr,!1,t)}function $c(e,n){e.uniform1iv(this.addr,n)}function Qc(e,n){e.uniform2iv(this.addr,n)}function Jc(e,n){e.uniform3iv(this.addr,n)}function jc(e,n){e.uniform4iv(this.addr,n)}function ef(e,n){e.uniform1uiv(this.addr,n)}function tf(e,n){e.uniform2uiv(this.addr,n)}function nf(e,n){e.uniform3uiv(this.addr,n)}function rf(e,n){e.uniform4uiv(this.addr,n)}function af(e,n,t){const i=this.cache,l=n.length,o=An(t,l);lt(i,o)||(e.uniform1iv(this.addr,o),ct(i,o));let d;this.type===e.SAMPLER_2D_SHADOW?d=Yn:d=Vr;for(let g=0;g!==l;++g)t.setTexture2D(n[g]||d,o[g])}function of(e,n,t){const i=this.cache,l=n.length,o=An(t,l);lt(i,o)||(e.uniform1iv(this.addr,o),ct(i,o));for(let d=0;d!==l;++d)t.setTexture3D(n[d]||kr,o[d])}function sf(e,n,t){const i=this.cache,l=n.length,o=An(t,l);lt(i,o)||(e.uniform1iv(this.addr,o),ct(i,o));for(let d=0;d!==l;++d)t.setTextureCube(n[d]||zr,o[d])}function lf(e,n,t){const i=this.cache,l=n.length,o=An(t,l);lt(i,o)||(e.uniform1iv(this.addr,o),ct(i,o));for(let d=0;d!==l;++d)t.setTexture2DArray(n[d]||Wr,o[d])}function cf(e){switch(e){case 5126:return kc;case 35664:return zc;case 35665:return Xc;case 35666:return Yc;case 35674:return Kc;case 35675:return qc;case 35676:return Zc;case 5124:case 35670:return $c;case 35667:case 35671:return Qc;case 35668:case 35672:return Jc;case 35669:case 35673:return jc;case 5125:return ef;case 36294:return tf;case 36295:return nf;case 36296:return rf;case 35678:case 36198:case 36298:case 36306:case 35682:return af;case 35679:case 36299:case 36307:return of;case 35680:case 36300:case 36308:case 36293:return sf;case 36289:case 36303:case 36311:case 36292:return lf}}class ff{constructor(n,t,i){this.id=n,this.addr=i,this.cache=[],this.type=t.type,this.setValue=Wc(t.type)}}class df{constructor(n,t,i){this.id=n,this.addr=i,this.cache=[],this.type=t.type,this.size=t.size,this.setValue=cf(t.type)}}class uf{constructor(n){this.id=n,this.seq=[],this.map={}}setValue(n,t,i){const l=this.seq;for(let o=0,d=l.length;o!==d;++o){const g=l[o];g.setValue(n,t[g.id],i)}}}const Gn=/(\w+)(\])?(\[|\.)?/g;function rr(e,n){e.seq.push(n),e.map[n.id]=n}function pf(e,n,t){const i=e.name,l=i.length;for(Gn.lastIndex=0;;){const o=Gn.exec(i),d=Gn.lastIndex;let g=o[1];const R=o[2]==="]",T=o[3];if(R&&(g=g|0),T===void 0||T==="["&&d+2===l){rr(t,T===void 0?new ff(g,e,n):new df(g,e,n));break}else{let I=t.map[g];I===void 0&&(I=new uf(g),rr(t,I)),t=I}}}class vn{constructor(n,t){this.seq=[],this.map={};const i=n.getProgramParameter(t,n.ACTIVE_UNIFORMS);for(let d=0;d<i;++d){const g=n.getActiveUniform(t,d),R=n.getUniformLocation(t,g.name);pf(g,R,this)}const l=[],o=[];for(const d of this.seq)d.type===n.SAMPLER_2D_SHADOW||d.type===n.SAMPLER_CUBE_SHADOW||d.type===n.SAMPLER_2D_ARRAY_SHADOW?l.push(d):o.push(d);l.length>0&&(this.seq=l.concat(o))}setValue(n,t,i,l){const o=this.map[t];o!==void 0&&o.setValue(n,i,l)}setOptional(n,t,i){const l=t[i];l!==void 0&&this.setValue(n,i,l)}static upload(n,t,i,l){for(let o=0,d=t.length;o!==d;++o){const g=t[o],R=i[g.id];R.needsUpdate!==!1&&g.setValue(n,R.value,l)}}static seqWithValue(n,t){const i=[];for(let l=0,o=n.length;l!==o;++l){const d=n[l];d.id in t&&i.push(d)}return i}}function ar(e,n,t){const i=e.createShader(n);return e.shaderSource(i,t),e.compileShader(i),i}const hf=37297;let mf=0;function _f(e,n){const t=e.split(`
`),i=[],l=Math.max(n-6,0),o=Math.min(n+6,t.length);for(let d=l;d<o;d++){const g=d+1;i.push(`${g===n?">":" "} ${g}: ${t[d]}`)}return i.join(`
`)}const or=new Fe;function gf(e){nt._getMatrix(or,nt.workingColorSpace,e);const n=`mat3( ${or.elements.map(t=>t.toFixed(4))} )`;switch(nt.getTransfer(e)){case Lr:return[n,"LinearTransferOETF"];case $e:return[n,"sRGBTransferOETF"];default:return We("WebGLProgram: Unsupported color space: ",e),[n,"LinearTransferOETF"]}}function sr(e,n,t){const i=e.getShaderParameter(n,e.COMPILE_STATUS),o=(e.getShaderInfoLog(n)||"").trim();if(i&&o==="")return"";const d=/ERROR: 0:(\d+)/.exec(o);if(d){const g=parseInt(d[1]);return t.toUpperCase()+`

`+o+`

`+_f(e.getShaderSource(n),g)}else return o}function vf(e,n){const t=gf(n);return[`vec4 ${e}( vec4 value ) {`,`	return ${t[1]}( vec4( value.rgb * ${t[0]}, value.a ) );`,"}"].join(`
`)}const Sf={[Fr]:"Linear",[yr]:"Reinhard",[Nr]:"Cineon",[Ir]:"ACESFilmic",[Dr]:"AgX",[wr]:"Neutral",[Ur]:"Custom"};function Ef(e,n){const t=Sf[n];return t===void 0?(We("WebGLProgram: Unsupported toneMapping:",n),"vec3 "+e+"( vec3 color ) { return LinearToneMapping( color ); }"):"vec3 "+e+"( vec3 color ) { return "+t+"ToneMapping( color ); }"}const hn=new Ne;function xf(){nt.getLuminanceCoefficients(hn);const e=hn.x.toFixed(4),n=hn.y.toFixed(4),t=hn.z.toFixed(4);return["float luminance( const in vec3 rgb ) {",`	const vec3 weights = vec3( ${e}, ${n}, ${t} );`,"	return dot( weights, rgb );","}"].join(`
`)}function Mf(e){return[e.extensionClipCullDistance?"#extension GL_ANGLE_clip_cull_distance : require":"",e.extensionMultiDraw?"#extension GL_ANGLE_multi_draw : require":""].filter(on).join(`
`)}function Tf(e){const n=[];for(const t in e){const i=e[t];i!==!1&&n.push("#define "+t+" "+i)}return n.join(`
`)}function Af(e,n){const t={},i=e.getProgramParameter(n,e.ACTIVE_ATTRIBUTES);for(let l=0;l<i;l++){const o=e.getActiveAttrib(n,l),d=o.name;let g=1;o.type===e.FLOAT_MAT2&&(g=2),o.type===e.FLOAT_MAT3&&(g=3),o.type===e.FLOAT_MAT4&&(g=4),t[d]={type:o.type,location:e.getAttribLocation(n,d),locationSize:g}}return t}function on(e){return e!==""}function lr(e,n){const t=n.numSpotLightShadows+n.numSpotLightMaps-n.numSpotLightShadowsWithMaps;return e.replace(/NUM_SUN_LIGHTS/g,n.numSunLights).replace(/NUM_DIR_LIGHTS/g,n.numDirLights).replace(/NUM_SPOT_LIGHTS/g,n.numSpotLights).replace(/NUM_SPOT_LIGHT_MAPS/g,n.numSpotLightMaps).replace(/NUM_SPOT_LIGHT_COORDS/g,t).replace(/NUM_RECT_AREA_LIGHTS/g,n.numRectAreaLights).replace(/NUM_POINT_LIGHTS/g,n.numPointLights).replace(/NUM_HEMI_LIGHTS/g,n.numHemiLights).replace(/NUM_SUN_LIGHT_SHADOWS/g,n.numSunLightShadows).replace(/NUM_DIR_LIGHT_SHADOWS/g,n.numDirLightShadows).replace(/NUM_SPOT_LIGHT_SHADOWS_WITH_MAPS/g,n.numSpotLightShadowsWithMaps).replace(/NUM_SPOT_LIGHT_SHADOWS/g,n.numSpotLightShadows).replace(/NUM_POINT_LIGHT_SHADOWS/g,n.numPointLightShadows)}function cr(e,n){return e.replace(/NUM_CLIPPING_PLANES/g,n.numClippingPlanes).replace(/UNION_CLIPPING_PLANES/g,n.numClippingPlanes-n.numClipIntersection)}const Rf=/^[ \t]*#include +<([\w\d./]+)>/gm;function Kn(e){return e.replace(Rf,Cf)}const bf=new Map;function Cf(e,n){let t=Le[n];if(t===void 0){const i=bf.get(n);if(i!==void 0)t=Le[i],We('WebGLRenderer: Shader chunk "%s" has been deprecated. Use "%s" instead.',n,i);else throw new Error("THREE.WebGLProgram: Can not resolve #include <"+n+">")}return Kn(t)}const Pf=/#pragma unroll_loop_start\s+for\s*\(\s*int\s+i\s*=\s*(\d+)\s*;\s*i\s*<\s*(\d+)\s*;\s*i\s*\+\+\s*\)\s*{([\s\S]+?)}\s+#pragma unroll_loop_end/g;function fr(e){return e.replace(Pf,Lf)}function Lf(e,n,t,i){let l="";for(let o=parseInt(n);o<parseInt(t);o++)l+=i.replace(/\[\s*i\s*\]/g,"[ "+o+" ]").replace(/UNROLLED_LOOP_INDEX/g,o);return l}function dr(e){let n=`precision ${e.precision} float;
	precision ${e.precision} int;
	precision ${e.precision} sampler2D;
	precision ${e.precision} samplerCube;
	precision ${e.precision} sampler3D;
	precision ${e.precision} sampler2DArray;
	precision ${e.precision} sampler2DShadow;
	precision ${e.precision} samplerCubeShadow;
	precision ${e.precision} sampler2DArrayShadow;
	precision ${e.precision} isampler2D;
	precision ${e.precision} isampler3D;
	precision ${e.precision} isamplerCube;
	precision ${e.precision} isampler2DArray;
	precision ${e.precision} usampler2D;
	precision ${e.precision} usampler3D;
	precision ${e.precision} usamplerCube;
	precision ${e.precision} usampler2DArray;
	`;return e.precision==="highp"?n+=`
#define HIGH_PRECISION`:e.precision==="mediump"?n+=`
#define MEDIUM_PRECISION`:e.precision==="lowp"&&(n+=`
#define LOW_PRECISION`),n}const Uf={[mn]:"SHADOWMAP_TYPE_PCF",[an]:"SHADOWMAP_TYPE_VSM"};function wf(e){return Uf[e.shadowMapType]||"SHADOWMAP_TYPE_BASIC"}const Df={[cn]:"ENVMAP_TYPE_CUBE",[jt]:"ENVMAP_TYPE_CUBE",[Mn]:"ENVMAP_TYPE_CUBE_UV"};function If(e){return e.envMap===!1?"ENVMAP_TYPE_CUBE":Df[e.envMapMode]||"ENVMAP_TYPE_CUBE"}const Nf={[jt]:"ENVMAP_MODE_REFRACTION"};function yf(e){return e.envMap===!1?"ENVMAP_MODE_REFLECTION":Nf[e.envMapMode]||"ENVMAP_MODE_REFLECTION"}const Ff={[ho]:"ENVMAP_BLENDING_MULTIPLY",[po]:"ENVMAP_BLENDING_MIX",[uo]:"ENVMAP_BLENDING_ADD"};function Of(e){return e.envMap===!1?"ENVMAP_BLENDING_NONE":Ff[e.combine]||"ENVMAP_BLENDING_NONE"}function Bf(e){const n=e.envMapCubeUVHeight;if(n===null)return null;const t=Math.log2(n)-2,i=1/n;return{texelWidth:1/(3*Math.max(Math.pow(2,t),112)),texelHeight:i,maxMip:t}}function Gf(e,n,t,i){const l=e.getContext(),o=t.defines;let d=t.vertexShader,g=t.fragmentShader;const R=wf(t),T=If(t),H=yf(t),I=Of(t),p=Bf(t),M=Mf(t),N=Tf(o),W=l.createProgram();let f,s,L=t.glslVersion?"#version "+t.glslVersion+`
`:"";t.isRawShaderMaterial?(f=["#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,N].filter(on).join(`
`),f.length>0&&(f+=`
`),s=["#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,N].filter(on).join(`
`),s.length>0&&(s+=`
`)):(f=[dr(t),"#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,N,t.extensionClipCullDistance?"#define USE_CLIP_DISTANCE":"",t.batching?"#define USE_BATCHING":"",t.batchingColor?"#define USE_BATCHING_COLOR":"",t.instancing?"#define USE_INSTANCING":"",t.instancingColor?"#define USE_INSTANCING_COLOR":"",t.instancingMorph?"#define USE_INSTANCING_MORPH":"",t.useFog&&t.fog?"#define USE_FOG":"",t.useFog&&t.fogExp2?"#define FOG_EXP2":"",t.map?"#define USE_MAP":"",t.envMap?"#define USE_ENVMAP":"",t.envMap?"#define "+H:"",t.lightMap?"#define USE_LIGHTMAP":"",t.aoMap?"#define USE_AOMAP":"",t.bumpMap?"#define USE_BUMPMAP":"",t.normalMap?"#define USE_NORMALMAP":"",t.normalMapObjectSpace?"#define USE_NORMALMAP_OBJECTSPACE":"",t.normalMapTangentSpace?"#define USE_NORMALMAP_TANGENTSPACE":"",t.displacementMap?"#define USE_DISPLACEMENTMAP":"",t.emissiveMap?"#define USE_EMISSIVEMAP":"",t.anisotropy?"#define USE_ANISOTROPY":"",t.anisotropyMap?"#define USE_ANISOTROPYMAP":"",t.clearcoatMap?"#define USE_CLEARCOATMAP":"",t.clearcoatRoughnessMap?"#define USE_CLEARCOAT_ROUGHNESSMAP":"",t.clearcoatNormalMap?"#define USE_CLEARCOAT_NORMALMAP":"",t.iridescenceMap?"#define USE_IRIDESCENCEMAP":"",t.iridescenceThicknessMap?"#define USE_IRIDESCENCE_THICKNESSMAP":"",t.specularMap?"#define USE_SPECULARMAP":"",t.specularColorMap?"#define USE_SPECULAR_COLORMAP":"",t.specularIntensityMap?"#define USE_SPECULAR_INTENSITYMAP":"",t.roughnessMap?"#define USE_ROUGHNESSMAP":"",t.metalnessMap?"#define USE_METALNESSMAP":"",t.alphaMap?"#define USE_ALPHAMAP":"",t.alphaHash?"#define USE_ALPHAHASH":"",t.transmission?"#define USE_TRANSMISSION":"",t.transmissionMap?"#define USE_TRANSMISSIONMAP":"",t.thicknessMap?"#define USE_THICKNESSMAP":"",t.sheenColorMap?"#define USE_SHEEN_COLORMAP":"",t.sheenRoughnessMap?"#define USE_SHEEN_ROUGHNESSMAP":"",t.mapUv?"#define MAP_UV "+t.mapUv:"",t.alphaMapUv?"#define ALPHAMAP_UV "+t.alphaMapUv:"",t.lightMapUv?"#define LIGHTMAP_UV "+t.lightMapUv:"",t.aoMapUv?"#define AOMAP_UV "+t.aoMapUv:"",t.emissiveMapUv?"#define EMISSIVEMAP_UV "+t.emissiveMapUv:"",t.bumpMapUv?"#define BUMPMAP_UV "+t.bumpMapUv:"",t.normalMapUv?"#define NORMALMAP_UV "+t.normalMapUv:"",t.displacementMapUv?"#define DISPLACEMENTMAP_UV "+t.displacementMapUv:"",t.metalnessMapUv?"#define METALNESSMAP_UV "+t.metalnessMapUv:"",t.roughnessMapUv?"#define ROUGHNESSMAP_UV "+t.roughnessMapUv:"",t.anisotropyMapUv?"#define ANISOTROPYMAP_UV "+t.anisotropyMapUv:"",t.clearcoatMapUv?"#define CLEARCOATMAP_UV "+t.clearcoatMapUv:"",t.clearcoatNormalMapUv?"#define CLEARCOAT_NORMALMAP_UV "+t.clearcoatNormalMapUv:"",t.clearcoatRoughnessMapUv?"#define CLEARCOAT_ROUGHNESSMAP_UV "+t.clearcoatRoughnessMapUv:"",t.iridescenceMapUv?"#define IRIDESCENCEMAP_UV "+t.iridescenceMapUv:"",t.iridescenceThicknessMapUv?"#define IRIDESCENCE_THICKNESSMAP_UV "+t.iridescenceThicknessMapUv:"",t.sheenColorMapUv?"#define SHEEN_COLORMAP_UV "+t.sheenColorMapUv:"",t.sheenRoughnessMapUv?"#define SHEEN_ROUGHNESSMAP_UV "+t.sheenRoughnessMapUv:"",t.specularMapUv?"#define SPECULARMAP_UV "+t.specularMapUv:"",t.specularColorMapUv?"#define SPECULAR_COLORMAP_UV "+t.specularColorMapUv:"",t.specularIntensityMapUv?"#define SPECULAR_INTENSITYMAP_UV "+t.specularIntensityMapUv:"",t.transmissionMapUv?"#define TRANSMISSIONMAP_UV "+t.transmissionMapUv:"",t.thicknessMapUv?"#define THICKNESSMAP_UV "+t.thicknessMapUv:"",t.vertexTangents&&t.flatShading===!1?"#define USE_TANGENT":"",t.vertexNormals?"#define HAS_NORMAL":"",t.vertexColors?"#define USE_COLOR":"",t.vertexAlphas?"#define USE_COLOR_ALPHA":"",t.vertexUv1s?"#define USE_UV1":"",t.vertexUv2s?"#define USE_UV2":"",t.vertexUv3s?"#define USE_UV3":"",t.pointsUvs?"#define USE_POINTS_UV":"",t.flatShading?"#define FLAT_SHADED":"",t.skinning?"#define USE_SKINNING":"",t.morphTargets?"#define USE_MORPHTARGETS":"",t.morphNormals&&t.flatShading===!1?"#define USE_MORPHNORMALS":"",t.morphColors?"#define USE_MORPHCOLORS":"",t.morphTargetsCount>0?"#define MORPHTARGETS_TEXTURE_STRIDE "+t.morphTextureStride:"",t.morphTargetsCount>0?"#define MORPHTARGETS_COUNT "+t.morphTargetsCount:"",t.doubleSided?"#define DOUBLE_SIDED":"",t.flipSided?"#define FLIP_SIDED":"",t.shadowMapEnabled?"#define USE_SHADOWMAP":"",t.shadowMapEnabled?"#define "+R:"",t.sizeAttenuation?"#define USE_SIZEATTENUATION":"",t.numLightProbes>0?"#define USE_LIGHT_PROBES":"",t.logarithmicDepthBuffer?"#define USE_LOGARITHMIC_DEPTH_BUFFER":"",t.reversedDepthBuffer?"#define USE_REVERSED_DEPTH_BUFFER":"","uniform mat4 modelMatrix;","uniform mat4 modelViewMatrix;","uniform mat4 projectionMatrix;","uniform mat4 viewMatrix;","uniform mat3 normalMatrix;","uniform vec3 cameraPosition;","uniform bool isOrthographic;","#ifdef USE_INSTANCING","	attribute mat4 instanceMatrix;","#endif","#ifdef USE_INSTANCING_COLOR","	attribute vec3 instanceColor;","#endif","#ifdef USE_INSTANCING_MORPH","	uniform sampler2D morphTexture;","#endif","attribute vec3 position;","attribute vec3 normal;","attribute vec2 uv;","#ifdef USE_UV1","	attribute vec2 uv1;","#endif","#ifdef USE_UV2","	attribute vec2 uv2;","#endif","#ifdef USE_UV3","	attribute vec2 uv3;","#endif","#ifdef USE_TANGENT","	attribute vec4 tangent;","#endif","#if defined( USE_COLOR_ALPHA )","	attribute vec4 color;","#elif defined( USE_COLOR )","	attribute vec3 color;","#endif","#ifdef USE_SKINNING","	attribute vec4 skinIndex;","	attribute vec4 skinWeight;","#endif",`
`].filter(on).join(`
`),s=[dr(t),"#define SHADER_TYPE "+t.shaderType,"#define SHADER_NAME "+t.shaderName,N,t.useFog&&t.fog?"#define USE_FOG":"",t.useFog&&t.fogExp2?"#define FOG_EXP2":"",t.alphaToCoverage?"#define ALPHA_TO_COVERAGE":"",t.map?"#define USE_MAP":"",t.matcap?"#define USE_MATCAP":"",t.envMap?"#define USE_ENVMAP":"",t.envMap?"#define "+T:"",t.envMap?"#define "+H:"",t.envMap?"#define "+I:"",p?"#define CUBEUV_TEXEL_WIDTH "+p.texelWidth:"",p?"#define CUBEUV_TEXEL_HEIGHT "+p.texelHeight:"",p?"#define CUBEUV_MAX_MIP "+p.maxMip+".0":"",t.lightMap?"#define USE_LIGHTMAP":"",t.aoMap?"#define USE_AOMAP":"",t.bumpMap?"#define USE_BUMPMAP":"",t.normalMap?"#define USE_NORMALMAP":"",t.normalMapObjectSpace?"#define USE_NORMALMAP_OBJECTSPACE":"",t.normalMapTangentSpace?"#define USE_NORMALMAP_TANGENTSPACE":"",t.packedNormalMap?"#define USE_PACKED_NORMALMAP":"",t.emissiveMap?"#define USE_EMISSIVEMAP":"",t.anisotropy?"#define USE_ANISOTROPY":"",t.anisotropyMap?"#define USE_ANISOTROPYMAP":"",t.clearcoat?"#define USE_CLEARCOAT":"",t.clearcoatMap?"#define USE_CLEARCOATMAP":"",t.clearcoatRoughnessMap?"#define USE_CLEARCOAT_ROUGHNESSMAP":"",t.clearcoatNormalMap?"#define USE_CLEARCOAT_NORMALMAP":"",t.dispersion?"#define USE_DISPERSION":"",t.retroreflection?"#define USE_RETROREFLECTION":"",t.iridescence?"#define USE_IRIDESCENCE":"",t.iridescenceMap?"#define USE_IRIDESCENCEMAP":"",t.iridescenceThicknessMap?"#define USE_IRIDESCENCE_THICKNESSMAP":"",t.specularMap?"#define USE_SPECULARMAP":"",t.specularColorMap?"#define USE_SPECULAR_COLORMAP":"",t.specularIntensityMap?"#define USE_SPECULAR_INTENSITYMAP":"",t.roughnessMap?"#define USE_ROUGHNESSMAP":"",t.metalnessMap?"#define USE_METALNESSMAP":"",t.alphaMap?"#define USE_ALPHAMAP":"",t.alphaTest?"#define USE_ALPHATEST":"",t.alphaHash?"#define USE_ALPHAHASH":"",t.sheen?"#define USE_SHEEN":"",t.sheenColorMap?"#define USE_SHEEN_COLORMAP":"",t.sheenRoughnessMap?"#define USE_SHEEN_ROUGHNESSMAP":"",t.transmission?"#define USE_TRANSMISSION":"",t.transmissionMap?"#define USE_TRANSMISSIONMAP":"",t.thicknessMap?"#define USE_THICKNESSMAP":"",t.vertexTangents&&t.flatShading===!1?"#define USE_TANGENT":"",t.vertexColors||t.instancingColor?"#define USE_COLOR":"",t.vertexAlphas||t.batchingColor?"#define USE_COLOR_ALPHA":"",t.vertexUv1s?"#define USE_UV1":"",t.vertexUv2s?"#define USE_UV2":"",t.vertexUv3s?"#define USE_UV3":"",t.pointsUvs?"#define USE_POINTS_UV":"",t.gradientMap?"#define USE_GRADIENTMAP":"",t.flatShading?"#define FLAT_SHADED":"",t.doubleSided?"#define DOUBLE_SIDED":"",t.flipSided?"#define FLIP_SIDED":"",t.shadowMapEnabled?"#define USE_SHADOWMAP":"",t.shadowMapEnabled?"#define "+R:"",t.premultipliedAlpha?"#define PREMULTIPLIED_ALPHA":"",t.numLightProbes>0?"#define USE_LIGHT_PROBES":"",t.numLightProbeGrids>0?"#define USE_LIGHT_PROBES_GRID":"",t.decodeVideoTexture?"#define DECODE_VIDEO_TEXTURE":"",t.decodeVideoTextureEmissive?"#define DECODE_VIDEO_TEXTURE_EMISSIVE":"",t.logarithmicDepthBuffer?"#define USE_LOGARITHMIC_DEPTH_BUFFER":"",t.reversedDepthBuffer?"#define USE_REVERSED_DEPTH_BUFFER":"","uniform mat4 viewMatrix;","uniform vec3 cameraPosition;","uniform bool isOrthographic;",t.toneMapping!==Pt?"#define TONE_MAPPING":"",t.toneMapping!==Pt?Le.tonemapping_pars_fragment:"",t.toneMapping!==Pt?Ef("toneMapping",t.toneMapping):"",t.dithering?"#define DITHERING":"",t.opaque?"#define OPAQUE":"",Le.colorspace_pars_fragment,vf("linearToOutputTexel",t.outputColorSpace),xf(),t.useDepthPacking?"#define DEPTH_PACKING "+t.depthPacking:"",`
`].filter(on).join(`
`)),d=Kn(d),d=lr(d,t),d=cr(d,t),g=Kn(g),g=lr(g,t),g=cr(g,t),d=fr(d),g=fr(g),t.isRawShaderMaterial!==!0&&(L=`#version 300 es
`,f=[M,"#define attribute in","#define varying out","#define texture2D texture"].join(`
`)+`
`+f,s=["#define varying in",t.glslVersion===Ki?"":"layout(location = 0) out highp vec4 pc_fragColor;",t.glslVersion===Ki?"":"#define gl_FragColor pc_fragColor","#define gl_FragDepthEXT gl_FragDepth","#define texture2D texture","#define textureCube texture","#define texture2DProj textureProj","#define texture2DLodEXT textureLod","#define texture2DProjLodEXT textureProjLod","#define textureCubeLodEXT textureLod","#define texture2DGradEXT textureGrad","#define texture2DProjGradEXT textureProjGrad","#define textureCubeGradEXT textureGrad"].join(`
`)+`
`+s);const z=L+f+d,h=L+s+g,S=ar(l,l.VERTEX_SHADER,z),m=ar(l,l.FRAGMENT_SHADER,h);l.attachShader(W,S),l.attachShader(W,m),t.index0AttributeName!==void 0?l.bindAttribLocation(W,0,t.index0AttributeName):t.hasPositionAttribute===!0&&l.bindAttribLocation(W,0,"position"),l.linkProgram(W);function w(F){if(e.debug.checkShaderErrors){const G=l.getProgramInfoLog(W)||"",q=l.getShaderInfoLog(S)||"",P=l.getShaderInfoLog(m)||"",Y=G.trim(),Q=q.trim(),K=P.trim();let ne=!0,Z=!0;if(l.getProgramParameter(W,l.LINK_STATUS)===!1)if(ne=!1,typeof e.debug.onShaderError=="function")e.debug.onShaderError(l,W,S,m);else{const j=sr(l,S,"vertex"),ee=sr(l,m,"fragment");Je("WebGLProgram: Shader Error "+l.getError()+" - VALIDATE_STATUS "+l.getProgramParameter(W,l.VALIDATE_STATUS)+`

Material Name: `+F.name+`
Material Type: `+F.type+`

Program Info Log: `+Y+`
`+j+`
`+ee)}else Y!==""?We("WebGLProgram: Program Info Log:",Y):(Q===""||K==="")&&(Z=!1);Z&&(F.diagnostics={runnable:ne,programLog:Y,vertexShader:{log:Q,prefix:f},fragmentShader:{log:K,prefix:s}})}l.deleteShader(S),l.deleteShader(m),c=new vn(l,W),_=Af(l,W)}let c;this.getUniforms=function(){return c===void 0&&w(this),c};let _;this.getAttributes=function(){return _===void 0&&w(this),_};let D=t.rendererExtensionParallelShaderCompile===!1;return this.isReady=function(){return D===!1&&(D=l.getProgramParameter(W,hf)),D},this.destroy=function(){i.releaseStatesOfProgram(this),l.deleteProgram(W),this.program=void 0},this.type=t.shaderType,this.name=t.shaderName,this.id=mf++,this.cacheKey=n,this.usedTimes=1,this.program=W,this.vertexShader=S,this.fragmentShader=m,this}let Hf=0;class Vf{constructor(){this.shaderCache=new Map,this.materialCache=new Map}update(n,t,i){const l=this._getShaderCacheForMaterial(n);return l.has(t)===!1&&(l.add(t),t.usedTimes++),l.has(i)===!1&&(l.add(i),i.usedTimes++),this}remove(n){const t=this.materialCache.get(n);for(const i of t)i.usedTimes--,i.usedTimes===0&&this.shaderCache.delete(i.code);return this.materialCache.delete(n),this}getVertexShaderStage(n){return this._getShaderStage(n.vertexShader)}getFragmentShaderStage(n){return this._getShaderStage(n.fragmentShader)}dispose(){this.shaderCache.clear(),this.materialCache.clear()}_getShaderCacheForMaterial(n){const t=this.materialCache;let i=t.get(n);return i===void 0&&(i=new Set,t.set(n,i)),i}_getShaderStage(n){const t=this.shaderCache;let i=t.get(n);return i===void 0&&(i=new Wf(n),t.set(n,i)),i}}class Wf{constructor(n){this.id=Hf++,this.code=n,this.usedTimes=0}}function kf(e){return e===Qt||e===zn||e===Xn}function zf(e,n,t,i,l,o){const d=new oo,g=new Vf,R=new Set,T=[],H=new Map,I=i.logarithmicDepthBuffer;let p=i.precision;const M={MeshDepthMaterial:"depth",MeshDistanceMaterial:"distance",MeshNormalMaterial:"normal",MeshBasicMaterial:"basic",MeshLambertMaterial:"lambert",MeshPhongMaterial:"phong",MeshToonMaterial:"toon",MeshStandardMaterial:"physical",MeshPhysicalMaterial:"physical",MeshMatcapMaterial:"matcap",LineBasicMaterial:"basic",LineDashedMaterial:"dashed",PointsMaterial:"points",ShadowMaterial:"shadow",SpriteMaterial:"sprite"};function N(c){return R.add(c),c===0?"uv":`uv${c}`}function W(c,_,D,F,G,q){const P=F.fog,Y=G.geometry,Q=c.isMeshStandardMaterial||c.isMeshLambertMaterial||c.isMeshPhongMaterial?F.environment:null,K=c.isMeshStandardMaterial||c.isMeshLambertMaterial&&!c.envMap||c.isMeshPhongMaterial&&!c.envMap,ne=n.get(c.envMap||Q,K),Z=ne&&ne.mapping===Mn?ne.image.height:null,j=M[c.type];c.precision!==null&&(p=i.getMaxPrecision(c.precision),p!==c.precision&&We("WebGLProgram.getParameters:",c.precision,"not supported, using",p,"instead."));const ee=Y.morphAttributes.position||Y.morphAttributes.normal||Y.morphAttributes.color,be=ee!==void 0?ee.length:0;let Re=0;Y.morphAttributes.position!==void 0&&(Re=1),Y.morphAttributes.normal!==void 0&&(Re=2),Y.morphAttributes.color!==void 0&&(Re=3);let it,ke,ze,V;if(j){const qe=bt[j];it=qe.vertexShader,ke=qe.fragmentShader}else{it=c.vertexShader,ke=c.fragmentShader;const qe=g.getVertexShaderStage(c),Ge=g.getFragmentShaderStage(c);g.update(c,qe,Ge),ze=qe.id,V=Ge.id}const $=e.getRenderTarget(),Ee=e.state.buffers.depth.getReversed(),Ue=G.isInstancedMesh===!0,me=G.isBatchedMesh===!0,ye=!!c.map,st=!!c.matcap,we=!!ne,Be=!!c.aoMap,Ke=!!c.lightMap,Ie=!!c.bumpMap&&c.wireframe===!1,je=!!c.normalMap,ft=!!c.displacementMap,ht=!!c.emissiveMap,tt=!!c.metalnessMap,at=!!c.roughnessMap,x=c.anisotropy>0,dt=c.clearcoat>0,Ve=c.dispersion>0,u=c.retroreflectivity>0,r=c.iridescence>0,A=c.sheen>0,U=c.transmission>0,O=x&&!!c.anisotropyMap,te=dt&&!!c.clearcoatMap,ie=dt&&!!c.clearcoatNormalMap,B=dt&&!!c.clearcoatRoughnessMap,X=r&&!!c.iridescenceMap,re=r&&!!c.iridescenceThicknessMap,xe=A&&!!c.sheenColorMap,le=A&&!!c.sheenRoughnessMap,ae=!!c.specularMap,Me=!!c.specularColorMap,Ae=!!c.specularIntensityMap,Ce=U&&!!c.transmissionMap,E=U&&!!c.thicknessMap,oe=!!c.gradientMap,k=!!c.alphaMap,se=c.alphaTest>0,ue=!!c.alphaHash,J=!!c.extensions;let Te=Pt;c.toneMapped&&($===null||$.isXRRenderTarget===!0)&&(Te=e.toneMapping);const ve={shaderID:j,shaderType:c.type,shaderName:c.name,vertexShader:it,fragmentShader:ke,defines:c.defines,customVertexShaderID:ze,customFragmentShaderID:V,isRawShaderMaterial:c.isRawShaderMaterial===!0,glslVersion:c.glslVersion,precision:p,batching:me,batchingColor:me&&G._colorsTexture!==null,instancing:Ue,instancingColor:Ue&&G.instanceColor!==null,instancingMorph:Ue&&G.morphTexture!==null,outputColorSpace:$===null?e.outputColorSpace:$.isXRRenderTarget===!0?$.texture.colorSpace:nt.workingColorSpace,alphaToCoverage:!!c.alphaToCoverage,map:ye,matcap:st,envMap:we,envMapMode:we&&ne.mapping,envMapCubeUVHeight:Z,aoMap:Be,lightMap:Ke,bumpMap:Ie,normalMap:je,displacementMap:ft,emissiveMap:ht,normalMapObjectSpace:je&&c.normalMapType===Qa,normalMapTangentSpace:je&&c.normalMapType===mi,packedNormalMap:je&&c.normalMapType===mi&&kf(c.normalMap.format),metalnessMap:tt,roughnessMap:at,anisotropy:x,anisotropyMap:O,clearcoat:dt,clearcoatMap:te,clearcoatNormalMap:ie,clearcoatRoughnessMap:B,dispersion:Ve,retroreflection:u,iridescence:r,iridescenceMap:X,iridescenceThicknessMap:re,sheen:A,sheenColorMap:xe,sheenRoughnessMap:le,specularMap:ae,specularColorMap:Me,specularIntensityMap:Ae,transmission:U,transmissionMap:Ce,thicknessMap:E,gradientMap:oe,opaque:c.transparent===!1&&c.blending===gn&&c.alphaToCoverage===!1,alphaMap:k,alphaTest:se,alphaHash:ue,combine:c.combine,mapUv:ye&&N(c.map.channel),aoMapUv:Be&&N(c.aoMap.channel),lightMapUv:Ke&&N(c.lightMap.channel),bumpMapUv:Ie&&N(c.bumpMap.channel),normalMapUv:je&&N(c.normalMap.channel),displacementMapUv:ft&&N(c.displacementMap.channel),emissiveMapUv:ht&&N(c.emissiveMap.channel),metalnessMapUv:tt&&N(c.metalnessMap.channel),roughnessMapUv:at&&N(c.roughnessMap.channel),anisotropyMapUv:O&&N(c.anisotropyMap.channel),clearcoatMapUv:te&&N(c.clearcoatMap.channel),clearcoatNormalMapUv:ie&&N(c.clearcoatNormalMap.channel),clearcoatRoughnessMapUv:B&&N(c.clearcoatRoughnessMap.channel),iridescenceMapUv:X&&N(c.iridescenceMap.channel),iridescenceThicknessMapUv:re&&N(c.iridescenceThicknessMap.channel),sheenColorMapUv:xe&&N(c.sheenColorMap.channel),sheenRoughnessMapUv:le&&N(c.sheenRoughnessMap.channel),specularMapUv:ae&&N(c.specularMap.channel),specularColorMapUv:Me&&N(c.specularColorMap.channel),specularIntensityMapUv:Ae&&N(c.specularIntensityMap.channel),transmissionMapUv:Ce&&N(c.transmissionMap.channel),thicknessMapUv:E&&N(c.thicknessMap.channel),alphaMapUv:k&&N(c.alphaMap.channel),vertexTangents:!!Y.attributes.tangent&&(je||x),vertexNormals:!!Y.attributes.normal,vertexColors:c.vertexColors,vertexAlphas:c.vertexColors===!0&&!!Y.attributes.color&&Y.attributes.color.itemSize===4,pointsUvs:G.isPoints===!0&&!!Y.attributes.uv&&(ye||k),fog:!!P,useFog:c.fog===!0,fogExp2:!!P&&P.isFogExp2,flatShading:c.wireframe===!1&&(c.flatShading===!0||Y.attributes.normal===void 0&&je===!1&&(c.isMeshLambertMaterial||c.isMeshPhongMaterial||c.isMeshStandardMaterial||c.isMeshPhysicalMaterial)),sizeAttenuation:c.sizeAttenuation===!0,logarithmicDepthBuffer:I,reversedDepthBuffer:Ee,skinning:G.isSkinnedMesh===!0,hasPositionAttribute:Y.attributes.position!==void 0,morphTargets:Y.morphAttributes.position!==void 0,morphNormals:Y.morphAttributes.normal!==void 0,morphColors:Y.morphAttributes.color!==void 0,morphTargetsCount:be,morphTextureStride:Re,numSunLights:_.sun.length,numDirLights:_.directional.length,numPointLights:_.point.length,numSpotLights:_.spot.length,numSpotLightMaps:_.spotLightMap.length,numRectAreaLights:_.rectArea.length,numHemiLights:_.hemi.length,numSunLightShadows:_.sunShadowMap.length,numDirLightShadows:_.directionalShadowMap.length,numPointLightShadows:_.pointShadowMap.length,numSpotLightShadows:_.spotShadowMap.length,numSpotLightShadowsWithMaps:_.numSpotLightShadowsWithMaps,numLightProbes:_.numLightProbes,numLightProbeGrids:q.length,numClippingPlanes:o.numPlanes,numClipIntersection:o.numIntersection,dithering:c.dithering,shadowMapEnabled:e.shadowMap.enabled&&D.length>0,shadowMapType:e.shadowMap.type,toneMapping:Te,decodeVideoTexture:ye&&c.map.isVideoTexture===!0&&nt.getTransfer(c.map.colorSpace)===$e,decodeVideoTextureEmissive:ht&&c.emissiveMap.isVideoTexture===!0&&nt.getTransfer(c.emissiveMap.colorSpace)===$e,premultipliedAlpha:c.premultipliedAlpha,doubleSided:c.side===Lt,flipSided:c.side===St,useDepthPacking:c.depthPacking>=0,depthPacking:c.depthPacking||0,index0AttributeName:c.index0AttributeName,extensionClipCullDistance:J&&c.extensions.clipCullDistance===!0&&t.has("WEBGL_clip_cull_distance"),extensionMultiDraw:(J&&c.extensions.multiDraw===!0||me)&&t.has("WEBGL_multi_draw"),rendererExtensionParallelShaderCompile:t.has("KHR_parallel_shader_compile"),customProgramCacheKey:c.customProgramCacheKey()};return ve.vertexUv1s=R.has(1),ve.vertexUv2s=R.has(2),ve.vertexUv3s=R.has(3),R.clear(),ve}function f(c){const _=[];if(c.shaderID?_.push(c.shaderID):(_.push(c.customVertexShaderID),_.push(c.customFragmentShaderID)),c.defines!==void 0)for(const D in c.defines)_.push(D),_.push(c.defines[D]);return c.isRawShaderMaterial===!1&&(s(_,c),L(_,c),_.push(e.outputColorSpace)),_.push(c.customProgramCacheKey),_.join()}function s(c,_){c.push(_.precision),c.push(_.outputColorSpace),c.push(_.envMapMode),c.push(_.envMapCubeUVHeight),c.push(_.mapUv),c.push(_.alphaMapUv),c.push(_.lightMapUv),c.push(_.aoMapUv),c.push(_.bumpMapUv),c.push(_.normalMapUv),c.push(_.displacementMapUv),c.push(_.emissiveMapUv),c.push(_.metalnessMapUv),c.push(_.roughnessMapUv),c.push(_.anisotropyMapUv),c.push(_.clearcoatMapUv),c.push(_.clearcoatNormalMapUv),c.push(_.clearcoatRoughnessMapUv),c.push(_.iridescenceMapUv),c.push(_.iridescenceThicknessMapUv),c.push(_.sheenColorMapUv),c.push(_.sheenRoughnessMapUv),c.push(_.specularMapUv),c.push(_.specularColorMapUv),c.push(_.specularIntensityMapUv),c.push(_.transmissionMapUv),c.push(_.thicknessMapUv),c.push(_.combine),c.push(_.fogExp2),c.push(_.sizeAttenuation),c.push(_.morphTargetsCount),c.push(_.morphAttributeCount),c.push(_.numSunLights),c.push(_.numDirLights),c.push(_.numPointLights),c.push(_.numSpotLights),c.push(_.numSpotLightMaps),c.push(_.numHemiLights),c.push(_.numRectAreaLights),c.push(_.numSunLightShadows),c.push(_.numDirLightShadows),c.push(_.numPointLightShadows),c.push(_.numSpotLightShadows),c.push(_.numSpotLightShadowsWithMaps),c.push(_.numLightProbes),c.push(_.shadowMapType),c.push(_.toneMapping),c.push(_.numClippingPlanes),c.push(_.numClipIntersection),c.push(_.depthPacking)}function L(c,_){d.disableAll(),_.instancing&&d.enable(0),_.instancingColor&&d.enable(1),_.instancingMorph&&d.enable(2),_.matcap&&d.enable(3),_.envMap&&d.enable(4),_.normalMapObjectSpace&&d.enable(5),_.normalMapTangentSpace&&d.enable(6),_.clearcoat&&d.enable(7),_.iridescence&&d.enable(8),_.alphaTest&&d.enable(9),_.vertexColors&&d.enable(10),_.vertexAlphas&&d.enable(11),_.vertexUv1s&&d.enable(12),_.vertexUv2s&&d.enable(13),_.vertexUv3s&&d.enable(14),_.vertexTangents&&d.enable(15),_.anisotropy&&d.enable(16),_.alphaHash&&d.enable(17),_.batching&&d.enable(18),_.dispersion&&d.enable(19),_.retroreflection&&d.enable(24),_.batchingColor&&d.enable(20),_.gradientMap&&d.enable(21),_.packedNormalMap&&d.enable(22),_.vertexNormals&&d.enable(23),c.push(d.mask),d.disableAll(),_.fog&&d.enable(0),_.useFog&&d.enable(1),_.flatShading&&d.enable(2),_.logarithmicDepthBuffer&&d.enable(3),_.reversedDepthBuffer&&d.enable(4),_.skinning&&d.enable(5),_.morphTargets&&d.enable(6),_.morphNormals&&d.enable(7),_.morphColors&&d.enable(8),_.premultipliedAlpha&&d.enable(9),_.shadowMapEnabled&&d.enable(10),_.doubleSided&&d.enable(11),_.flipSided&&d.enable(12),_.useDepthPacking&&d.enable(13),_.dithering&&d.enable(14),_.transmission&&d.enable(15),_.sheen&&d.enable(16),_.opaque&&d.enable(17),_.pointsUvs&&d.enable(18),_.decodeVideoTexture&&d.enable(19),_.decodeVideoTextureEmissive&&d.enable(20),_.alphaToCoverage&&d.enable(21),_.numLightProbeGrids>0&&d.enable(22),_.hasPositionAttribute&&d.enable(23),c.push(d.mask)}function z(c){const _=M[c.type];let D;if(_){const F=bt[_];D=$a.clone(F.uniforms)}else D=c.uniforms;return D}function h(c,_){let D=H.get(_);return D!==void 0?++D.usedTimes:(D=new Gf(e,_,c,l),T.push(D),H.set(_,D)),D}function S(c){if(--c.usedTimes===0){const _=T.indexOf(c);T[_]=T[T.length-1],T.pop(),H.delete(c.cacheKey),c.destroy()}}function m(c){g.remove(c)}function w(){g.dispose()}return{getParameters:W,getProgramCacheKey:f,getUniforms:z,acquireProgram:h,releaseProgram:S,releaseShaderCache:m,programs:T,dispose:w}}function Xf(){let e=new WeakMap;function n(d){return e.has(d)}function t(d){let g=e.get(d);return g===void 0&&(g={},e.set(d,g)),g}function i(d){e.delete(d)}function l(d,g,R){e.get(d)[g]=R}function o(){e=new WeakMap}return{has:n,get:t,remove:i,update:l,dispose:o}}function Yf(e,n){return e.groupOrder!==n.groupOrder?e.groupOrder-n.groupOrder:e.renderOrder!==n.renderOrder?e.renderOrder-n.renderOrder:e.material.id!==n.material.id?e.material.id-n.material.id:e.materialVariant!==n.materialVariant?e.materialVariant-n.materialVariant:e.z!==n.z?e.z-n.z:e.id-n.id}function ur(e,n){return e.groupOrder!==n.groupOrder?e.groupOrder-n.groupOrder:e.renderOrder!==n.renderOrder?e.renderOrder-n.renderOrder:e.z!==n.z?n.z-e.z:e.id-n.id}function pr(){const e=[];let n=0;const t=[],i=[],l=[];function o(){n=0,t.length=0,i.length=0,l.length=0}function d(p){let M=0;return p.isInstancedMesh&&(M+=2),p.isSkinnedMesh&&(M+=1),M}function g(p,M,N,W,f,s){let L=e[n];return L===void 0?(L={id:p.id,object:p,geometry:M,material:N,materialVariant:d(p),groupOrder:W,renderOrder:p.renderOrder,z:f,group:s},e[n]=L):(L.id=p.id,L.object=p,L.geometry=M,L.material=N,L.materialVariant=d(p),L.groupOrder=W,L.renderOrder=p.renderOrder,L.z=f,L.group=s),n++,L}function R(p,M,N,W,f,s,L){L.reversedDepth===!0&&(f=-f);const z=g(p,M,N,W,f,s);N.transmission>0?i.push(z):N.transparent===!0?l.push(z):t.push(z)}function T(p,M,N,W,f,s){const L=g(p,M,N,W,f,s);N.transmission>0?i.unshift(L):N.transparent===!0?l.unshift(L):t.unshift(L)}function H(p,M){t.length>1&&t.sort(p||Yf),i.length>1&&i.sort(M||ur),l.length>1&&l.sort(M||ur)}function I(){for(let p=n,M=e.length;p<M;p++){const N=e[p];if(N.id===null)break;N.id=null,N.object=null,N.geometry=null,N.material=null,N.group=null}}return{opaque:t,transmissive:i,transparent:l,init:o,push:R,unshift:T,finish:I,sort:H}}function Kf(){let e=new WeakMap;function n(i,l){const o=e.get(i);let d;return o===void 0?(d=new pr,e.set(i,[d])):l>=o.length?(d=new pr,o.push(d)):d=o[l],d}function t(){e=new WeakMap}return{get:n,dispose:t}}function qf(){const e={};return{get:function(n){if(e[n.id]!==void 0)return e[n.id];let t;switch(n.type){case"SunLight":case"DirectionalLight":t={direction:new Ne,color:new et};break;case"SpotLight":t={position:new Ne,direction:new Ne,color:new et,distance:0,coneCos:0,penumbraCos:0,decay:0};break;case"PointLight":t={position:new Ne,color:new et,distance:0,decay:0};break;case"HemisphereLight":t={direction:new Ne,skyColor:new et,groundColor:new et};break;case"RectAreaLight":t={color:new et,position:new Ne,halfWidth:new Ne,halfHeight:new Ne};break}return e[n.id]=t,t}}}function Zf(){const e={};return{get:function(n){if(e[n.id]!==void 0)return e[n.id];let t;switch(n.type){case"SunLight":case"DirectionalLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new gt};break;case"SpotLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new gt};break;case"PointLight":t={shadowIntensity:1,shadowBias:0,shadowNormalBias:0,shadowRadius:1,shadowMapSize:new gt,shadowCameraNear:1,shadowCameraFar:1e3};break}return e[n.id]=t,t}}}let $f=0;function Qf(e,n){return(n.castShadow?2:0)-(e.castShadow?2:0)+(n.map?1:0)-(e.map?1:0)}function Jf(e){const n=new qf,t=Zf(),i={version:0,hash:{sunLength:-1,directionalLength:-1,pointLength:-1,spotLength:-1,rectAreaLength:-1,hemiLength:-1,numSunShadows:-1,numDirectionalShadows:-1,numPointShadows:-1,numSpotShadows:-1,numSpotMaps:-1,numLightProbes:-1},ambient:[0,0,0],probe:[],sun:[],sunShadow:[],sunShadowMap:[],sunShadowMatrix:[],sunShadowCascade:[],directional:[],directionalShadow:[],directionalShadowMap:[],directionalShadowMatrix:[],spot:[],spotLightMap:[],spotShadow:[],spotShadowMap:[],spotLightMatrix:[],rectArea:[],rectAreaLTC1:null,rectAreaLTC2:null,point:[],pointShadow:[],pointShadowMap:[],pointShadowMatrix:[],hemi:[],numSpotLightShadowsWithMaps:0,numLightProbes:0};for(let T=0;T<9;T++)i.probe.push(new Ne);const l=new Ne,o=new $t,d=new $t;function g(T){let H=0,I=0,p=0;for(let G=0;G<9;G++)i.probe[G].set(0,0,0);let M=0,N=0,W=0,f=0,s=0,L=0,z=0,h=0,S=0,m=0,w=0,c=0,_=0,D=0;T.sort(Qf);for(let G=0,q=T.length;G<q;G++){const P=T[G],Y=P.color,Q=P.intensity,K=P.distance;let ne=null;if(P.shadow&&P.shadow.map&&(P.shadow.map.texture.format===Qt?ne=P.shadow.map.texture:ne=P.shadow.map.depthTexture||P.shadow.map.texture),P.isAmbientLight)H+=Y.r*Q,I+=Y.g*Q,p+=Y.b*Q;else if(P.isLightProbe){for(let Z=0;Z<9;Z++)i.probe[Z].addScaledVector(P.sh.coefficients[Z],Q);D++}else if(P.isSunLight){const Z=n.get(P);if(Z.color.copy(P.color).multiplyScalar(P.intensity),P.castShadow){const j=P.shadow,ee=t.get(P);ee.shadowIntensity=j.intensity,ee.shadowBias=j.bias,ee.shadowNormalBias=j.normalBias,ee.shadowRadius=j.radius,ee.shadowMapSize.copy(j.mapSize).multiply(j.getFrameExtents()),i.sunShadow[N]=ee,i.sunShadowMap[N]=ne;const be=j.getViewportCount();for(let Re=0;Re<be;Re++)i.sunShadowMatrix[W+Re]=j.getMatrix(Re),i.sunShadowCascade[W+Re]=j._cascadeData[Re];W+=be,N++}i.sun[M]=Z,M++}else if(P.isDirectionalLight){const Z=n.get(P);if(Z.color.copy(P.color).multiplyScalar(P.intensity),P.castShadow){const j=P.shadow,ee=t.get(P);ee.shadowIntensity=j.intensity,ee.shadowBias=j.bias,ee.shadowNormalBias=j.normalBias,ee.shadowRadius=j.radius,ee.shadowMapSize=j.mapSize,i.directionalShadow[f]=ee,i.directionalShadowMap[f]=ne,i.directionalShadowMatrix[f]=P.shadow.matrix,S++}i.directional[f]=Z,f++}else if(P.isSpotLight){const Z=n.get(P);Z.position.setFromMatrixPosition(P.matrixWorld),Z.color.copy(Y).multiplyScalar(Q),Z.distance=K,Z.coneCos=Math.cos(P.angle),Z.penumbraCos=Math.cos(P.angle*(1-P.penumbra)),Z.decay=P.decay,i.spot[L]=Z;const j=P.shadow;if(P.map&&(i.spotLightMap[c]=P.map,c++,j.updateMatrices(P),P.castShadow&&_++),i.spotLightMatrix[L]=j.matrix,P.castShadow){const ee=t.get(P);ee.shadowIntensity=j.intensity,ee.shadowBias=j.bias,ee.shadowNormalBias=j.normalBias,ee.shadowRadius=j.radius,ee.shadowMapSize=j.mapSize,i.spotShadow[L]=ee,i.spotShadowMap[L]=ne,w++}L++}else if(P.isRectAreaLight){const Z=n.get(P);Z.color.copy(Y).multiplyScalar(Q),Z.halfWidth.set(P.width*.5,0,0),Z.halfHeight.set(0,P.height*.5,0),i.rectArea[z]=Z,z++}else if(P.isPointLight){const Z=n.get(P);if(Z.color.copy(P.color).multiplyScalar(P.intensity),Z.distance=P.distance,Z.decay=P.decay,P.castShadow){const j=P.shadow,ee=t.get(P);ee.shadowIntensity=j.intensity,ee.shadowBias=j.bias,ee.shadowNormalBias=j.normalBias,ee.shadowRadius=j.radius,ee.shadowMapSize=j.mapSize,ee.shadowCameraNear=j.camera.near,ee.shadowCameraFar=j.camera.far,i.pointShadow[s]=ee,i.pointShadowMap[s]=ne,i.pointShadowMatrix[s]=P.shadow.matrix,m++}i.point[s]=Z,s++}else if(P.isHemisphereLight){const Z=n.get(P);Z.skyColor.copy(P.color).multiplyScalar(Q),Z.groundColor.copy(P.groundColor).multiplyScalar(Q),i.hemi[h]=Z,h++}}z>0&&(e.has("OES_texture_float_linear")===!0?(i.rectAreaLTC1=ce.LTC_FLOAT_1,i.rectAreaLTC2=ce.LTC_FLOAT_2):(i.rectAreaLTC1=ce.LTC_HALF_1,i.rectAreaLTC2=ce.LTC_HALF_2)),i.ambient[0]=H,i.ambient[1]=I,i.ambient[2]=p;const F=i.hash;(F.sunLength!==M||F.directionalLength!==f||F.pointLength!==s||F.spotLength!==L||F.rectAreaLength!==z||F.hemiLength!==h||F.numSunShadows!==N||F.numDirectionalShadows!==S||F.numPointShadows!==m||F.numSpotShadows!==w||F.numSpotMaps!==c||F.numLightProbes!==D)&&(i.sun.length=M,i.directional.length=f,i.spot.length=L,i.rectArea.length=z,i.point.length=s,i.hemi.length=h,i.sunShadow.length=N,i.sunShadowMap.length=N,i.sunShadowMatrix.length=W,i.sunShadowCascade.length=W,i.directionalShadow.length=S,i.directionalShadowMap.length=S,i.directionalShadowMatrix.length=S,i.pointShadow.length=m,i.pointShadowMap.length=m,i.pointShadowMatrix.length=m,i.spotShadow.length=w,i.spotShadowMap.length=w,i.spotLightMatrix.length=w+c-_,i.spotLightMap.length=c,i.numSpotLightShadowsWithMaps=_,i.numLightProbes=D,F.sunLength=M,F.directionalLength=f,F.pointLength=s,F.spotLength=L,F.rectAreaLength=z,F.hemiLength=h,F.numSunShadows=N,F.numDirectionalShadows=S,F.numPointShadows=m,F.numSpotShadows=w,F.numSpotMaps=c,F.numLightProbes=D,i.version=$f++)}function R(T,H){let I=0,p=0,M=0,N=0,W=0,f=0;const s=H.matrixWorldInverse;for(let L=0,z=T.length;L<z;L++){const h=T[L];if(h.isSunLight){const S=i.sun[I];S.direction.setFromMatrixPosition(h.matrixWorld),S.direction.transformDirection(s),I++}else if(h.isDirectionalLight){const S=i.directional[p];S.direction.setFromMatrixPosition(h.matrixWorld),l.setFromMatrixPosition(h.target.matrixWorld),S.direction.sub(l),S.direction.transformDirection(s),p++}else if(h.isSpotLight){const S=i.spot[N];S.position.setFromMatrixPosition(h.matrixWorld),S.position.applyMatrix4(s),S.direction.setFromMatrixPosition(h.matrixWorld),l.setFromMatrixPosition(h.target.matrixWorld),S.direction.sub(l),S.direction.transformDirection(s),N++}else if(h.isRectAreaLight){const S=i.rectArea[W];S.position.setFromMatrixPosition(h.matrixWorld),S.position.applyMatrix4(s),d.identity(),o.copy(h.matrixWorld),o.premultiply(s),d.extractRotation(o),S.halfWidth.set(h.width*.5,0,0),S.halfHeight.set(0,h.height*.5,0),S.halfWidth.applyMatrix4(d),S.halfHeight.applyMatrix4(d),W++}else if(h.isPointLight){const S=i.point[M];S.position.setFromMatrixPosition(h.matrixWorld),S.position.applyMatrix4(s),M++}else if(h.isHemisphereLight){const S=i.hemi[f];S.direction.setFromMatrixPosition(h.matrixWorld),S.direction.transformDirection(s),f++}}}return{setup:g,setupView:R,state:i}}function hr(e){const n=new Jf(e),t=[],i=[],l=[];function o(p){I.camera=p,t.length=0,i.length=0,l.length=0}function d(p){t.push(p)}function g(p){i.push(p)}function R(p){l.push(p)}function T(){n.setup(t)}function H(p){n.setupView(t,p)}const I={lightsArray:t,shadowsArray:i,lightProbeGridArray:l,camera:null,lights:n,transmissionRenderTarget:{},textureUnits:0};return{init:o,state:I,setupLights:T,setupLightsView:H,pushLight:d,pushShadow:g,pushLightProbeGrid:R}}function jf(e){let n=new WeakMap;function t(l,o=0){const d=n.get(l);let g;return d===void 0?(g=new hr(e),n.set(l,[g])):o>=d.length?(g=new hr(e),d.push(g)):g=d[o],g}function i(){n=new WeakMap}return{get:t,dispose:i}}const ed=`void main() {
	gl_Position = vec4( position, 1.0 );
}`,td=`uniform sampler2D shadow_pass;
uniform vec2 resolution;
uniform float radius;
void main() {
	const float samples = float( VSM_SAMPLES );
	float mean = 0.0;
	float squared_mean = 0.0;
	float uvStride = samples <= 1.0 ? 0.0 : 2.0 / ( samples - 1.0 );
	float uvStart = samples <= 1.0 ? 0.0 : - 1.0;
	for ( float i = 0.0; i < samples; i ++ ) {
		float uvOffset = uvStart + i * uvStride;
		#ifdef HORIZONTAL_PASS
			vec2 distribution = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( uvOffset, 0.0 ) * radius ) / resolution ).rg;
			mean += distribution.x;
			squared_mean += distribution.y * distribution.y + distribution.x * distribution.x;
		#else
			float depth = texture2D( shadow_pass, ( gl_FragCoord.xy + vec2( 0.0, uvOffset ) * radius ) / resolution ).r;
			mean += depth;
			squared_mean += depth * depth;
		#endif
	}
	mean = mean / samples;
	squared_mean = squared_mean / samples;
	float std_dev = sqrt( max( 0.0, squared_mean - mean * mean ) );
	gl_FragColor = vec4( mean, std_dev, 0.0, 1.0 );
}`,nd=[new Ne(1,0,0),new Ne(-1,0,0),new Ne(0,1,0),new Ne(0,-1,0),new Ne(0,0,1),new Ne(0,0,-1)],id=[new Ne(0,-1,0),new Ne(0,-1,0),new Ne(0,0,1),new Ne(0,0,-1),new Ne(0,-1,0),new Ne(0,-1,0)],mr=new $t,rn=new Ne,Hn=new Ne;function rd(e,n,t){let i=new _r;const l=new gt,o=new gt,d=new _t,g=new La,R=new Ua,T={},H=t.maxTextureSize,I={[sn]:St,[St]:sn,[Lt]:Lt},p=new It({defines:{VSM_SAMPLES:8},uniforms:{shadow_pass:{value:null},resolution:{value:new gt},radius:{value:4}},vertexShader:ed,fragmentShader:td}),M=p.clone();M.defines.HORIZONTAL_PASS=1;const N=new xn;N.setAttribute("position",new Wn(new Float32Array([-1,-1,.5,3,-1,.5,-1,3,.5]),3));const W=new Nt(N,p),f=this;this.enabled=!1,this.autoUpdate=!0,this.needsUpdate=!1,this.type=mn;let s=this.type;this.render=function(m,w,c){if(f.enabled===!1||f.autoUpdate===!1&&f.needsUpdate===!1||m.length===0)return;this.type===wa&&(We("WebGLShadowMap: PCFSoftShadowMap has been removed. Using PCFShadowMap instead."),this.type=mn);const _=e.getRenderTarget(),D=e.getActiveCubeFace(),F=e.getActiveMipmapLevel(),G=e.state;G.setBlending(wt),G.buffers.depth.getReversed()===!0?G.buffers.color.setClear(0,0,0,0):G.buffers.color.setClear(1,1,1,1),G.buffers.depth.setTest(!0),G.setScissorTest(!1);const q=s!==this.type;q&&w.traverse(function(P){P.material&&(Array.isArray(P.material)?P.material.forEach(Y=>Y.needsUpdate=!0):P.material.needsUpdate=!0)});for(let P=0,Y=m.length;P<Y;P++){const Q=m[P],K=Q.shadow;if(K===void 0){We("WebGLShadowMap:",Q,"has no shadow.");continue}if(K.autoUpdate===!1&&K.needsUpdate===!1)continue;l.copy(K.mapSize);const ne=K.getFrameExtents();l.multiply(ne),o.copy(K.mapSize),(l.x>H||l.y>H)&&(l.x>H&&(o.x=Math.floor(H/ne.x),l.x=o.x*ne.x,K.mapSize.x=o.x),l.y>H&&(o.y=Math.floor(H/ne.y),l.y=o.y*ne.y,K.mapSize.y=o.y));const Z=e.state.buffers.depth.getReversed();if(K.camera._reversedDepth=Z,K.map===null||q===!0){if(K.map!==null&&(K.map.depthTexture!==null&&(K.map.depthTexture.dispose(),K.map.depthTexture=null),K.map.dispose()),this.type===an){if(Q.isPointLight){We("WebGLShadowMap: VSM shadow maps are not supported for PointLights. Use PCF or BasicShadowMap instead.");continue}K.map=new Mt(l.x,l.y,{format:Qt,type:Dt,minFilter:vt,magFilter:vt,generateMipmaps:!1}),K.map.texture.name=Q.name+".shadowMap",K.map.depthTexture=new Sn(l.x,l.y,Bt),K.map.depthTexture.name=Q.name+".shadowMapDepth",K.map.depthTexture.format=Jt,K.map.depthTexture.compareFunction=null,K.map.depthTexture.minFilter=Vt,K.map.depthTexture.magFilter=Vt}else Q.isPointLight?(K.map=new Hr(l.x),K.map.depthTexture=new Da(l.x,Wt)):(K.map=new Mt(l.x,l.y),K.map.depthTexture=new Sn(l.x,l.y,Wt)),K.map.depthTexture.name=Q.name+".shadowMap",K.map.depthTexture.format=Jt,this.type===mn?(K.map.depthTexture.compareFunction=Z?qn:Zn,K.map.depthTexture.minFilter=vt,K.map.depthTexture.magFilter=vt):(K.map.depthTexture.compareFunction=null,K.map.depthTexture.minFilter=Vt,K.map.depthTexture.magFilter=Vt);K.camera.updateProjectionMatrix()}K.map.isWebGLCubeRenderTarget!==!0&&(K.map.width!==l.x||K.map.height!==l.y)&&K.map.setSize(l.x,l.y);const j=K.map.isWebGLCubeRenderTarget?6:K.getViewportCount();Q.isPointLight!==!0&&K.updateMatrices(Q,c);for(let ee=0;ee<j;ee++){const be=K.getCamera(ee);if(Q.isPointLight){const Re=K.camera,it=K.matrix,ke=Q.distance||Re.far;ke!==Re.far&&(Re.far=ke,Re.updateProjectionMatrix()),rn.setFromMatrixPosition(Q.matrixWorld),Re.position.copy(rn),Hn.copy(Re.position),Hn.add(nd[ee]),Re.up.copy(id[ee]),Re.lookAt(Hn),Re.updateMatrixWorld(),it.makeTranslation(-rn.x,-rn.y,-rn.z),mr.multiplyMatrices(Re.projectionMatrix,Re.matrixWorldInverse),K._frustum.setFromProjectionMatrix(mr,Re.coordinateSystem,Re.reversedDepth)}if(K.map.isWebGLCubeRenderTarget)e.setRenderTarget(K.map,ee),e.clear();else{ee===0&&(e.setRenderTarget(K.map),e.clear());const Re=K.getViewport(ee);d.set(o.x*Re.x,o.y*Re.y,o.x*Re.z,o.y*Re.w),G.viewport(d)}i=K.getFrustum(ee),h(w,c,be,Q,this.type)}K.isPointLightShadow!==!0&&this.type===an&&L(K,c),K.needsUpdate=!1}s=this.type,f.needsUpdate=!1,e.setRenderTarget(_,D,F)};function L(m,w){const c=n.update(W);p.defines.VSM_SAMPLES!==m.blurSamples&&(p.defines.VSM_SAMPLES=m.blurSamples,M.defines.VSM_SAMPLES=m.blurSamples,p.needsUpdate=!0,M.needsUpdate=!0),m.mapPass===null?m.mapPass=new Mt(l.x,l.y,{format:Qt,type:Dt}):(m.mapPass.width!==m.map.width||m.mapPass.height!==m.map.height)&&m.mapPass.setSize(m.map.width,m.map.height),p.uniforms.shadow_pass.value=m.map.depthTexture,p.uniforms.resolution.value.set(m.map.width,m.map.height),p.uniforms.radius.value=m.radius,e.setRenderTarget(m.mapPass),e.clear(),e.renderBufferDirect(w,null,c,p,W,null),M.uniforms.shadow_pass.value=m.mapPass.texture,M.uniforms.resolution.value.set(m.map.width,m.map.height),M.uniforms.radius.value=m.radius,e.setRenderTarget(m.map),e.clear(),e.renderBufferDirect(w,null,c,M,W,null)}function z(m,w,c,_){let D=null;const F=c.isPointLight===!0?m.customDistanceMaterial:m.customDepthMaterial;if(F!==void 0)D=F;else if(D=c.isPointLight===!0?R:g,e.localClippingEnabled&&w.clipShadows===!0&&Array.isArray(w.clippingPlanes)&&w.clippingPlanes.length!==0||w.displacementMap&&w.displacementScale!==0||w.alphaMap&&w.alphaTest>0||w.map&&w.alphaTest>0||w.alphaToCoverage===!0){const G=D.uuid,q=w.uuid;let P=T[G];P===void 0&&(P={},T[G]=P);let Y=P[q];Y===void 0&&(Y=D.clone(),P[q]=Y,w.addEventListener("dispose",S)),D=Y}if(D.visible=w.visible,D.wireframe=w.wireframe,_===an?D.side=w.shadowSide!==null?w.shadowSide:w.side:D.side=w.shadowSide!==null?w.shadowSide:I[w.side],D.alphaMap=w.alphaMap,D.alphaTest=w.alphaToCoverage===!0?.5:w.alphaTest,D.map=w.map,D.clipShadows=w.clipShadows,D.clippingPlanes=w.clippingPlanes,D.clipIntersection=w.clipIntersection,D.displacementMap=w.displacementMap,D.displacementScale=w.displacementScale,D.displacementBias=w.displacementBias,D.wireframeLinewidth=w.wireframeLinewidth,D.linewidth=w.linewidth,c.isPointLight===!0&&D.isMeshDistanceMaterial===!0){const G=e.properties.get(D);G.light=c}return D}function h(m,w,c,_,D){if(m.visible===!1)return;if(m.layers.test(w.layers)&&(m.isMesh||m.isLine||m.isPoints)&&(m.castShadow||m.receiveShadow&&D===an)&&(!m.frustumCulled||m.intersectsFrustum(i))){m.modelViewMatrix.multiplyMatrices(c.matrixWorldInverse,m.matrixWorld);const q=n.update(m),P=m.material;if(Array.isArray(P)){const Y=q.groups;for(let Q=0,K=Y.length;Q<K;Q++){const ne=Y[Q],Z=P[ne.materialIndex];if(Z&&Z.visible){const j=z(m,Z,_,D);m.onBeforeShadow(e,m,w,c,q,j,ne),e.renderBufferDirect(c,null,q,j,m,ne),m.onAfterShadow(e,m,w,c,q,j,ne)}}}else if(P.visible){const Y=z(m,P,_,D);m.onBeforeShadow(e,m,w,c,q,Y,null),e.renderBufferDirect(c,null,q,Y,m,null),m.onAfterShadow(e,m,w,c,q,Y,null)}}const G=m.children;for(let q=0,P=G.length;q<P;q++)h(G[q],w,c,_,D)}function S(m){m.target.removeEventListener("dispose",S);for(const c in T){const _=T[c],D=m.target.uuid;D in _&&(_[D].dispose(),delete _[D])}}}function ad(e,n){function t(){let E=!1;const oe=new _t;let k=null;const se=new _t(0,0,0,0);return{setMask:function(ue){k!==ue&&!E&&(e.colorMask(ue,ue,ue,ue),k=ue)},setLocked:function(ue){E=ue},setClear:function(ue,J,Te,ve,qe){qe===!0&&(ue*=ve,J*=ve,Te*=ve),oe.set(ue,J,Te,ve),se.equals(oe)===!1&&(e.clearColor(ue,J,Te,ve),se.copy(oe))},reset:function(){E=!1,k=null,se.set(-1,0,0,0)}}}function i(){let E=!1,oe=!1,k=null,se=null,ue=null;return{setReversed:function(J){if(oe!==J){const Te=n.get("EXT_clip_control");J?Te.clipControlEXT(Te.LOWER_LEFT_EXT,Te.ZERO_TO_ONE_EXT):Te.clipControlEXT(Te.LOWER_LEFT_EXT,Te.NEGATIVE_ONE_TO_ONE_EXT),oe=J;const ve=ue;ue=null,this.setClear(ve)}},getReversed:function(){return oe},setTest:function(J){J?$(e.DEPTH_TEST):Ee(e.DEPTH_TEST)},setMask:function(J){k!==J&&!E&&(e.depthMask(J),k=J)},setFunc:function(J){if(oe&&(J=go[J]),se!==J){switch(J){case Ya:e.depthFunc(e.NEVER);break;case Xa:e.depthFunc(e.ALWAYS);break;case za:e.depthFunc(e.LESS);break;case ci:e.depthFunc(e.LEQUAL);break;case ka:e.depthFunc(e.EQUAL);break;case Wa:e.depthFunc(e.GEQUAL);break;case Va:e.depthFunc(e.GREATER);break;case Ha:e.depthFunc(e.NOTEQUAL);break;default:e.depthFunc(e.LEQUAL)}se=J}},setLocked:function(J){E=J},setClear:function(J){ue!==J&&(ue=J,oe&&(J=1-J),e.clearDepth(J))},reset:function(){E=!1,k=null,se=null,ue=null,oe=!1}}}function l(){let E=!1,oe=null,k=null,se=null,ue=null,J=null,Te=null,ve=null,qe=null;return{setTest:function(Ge){E||(Ge?$(e.STENCIL_TEST):Ee(e.STENCIL_TEST))},setMask:function(Ge){oe!==Ge&&!E&&(e.stencilMask(Ge),oe=Ge)},setFunc:function(Ge,xt,Tt){(k!==Ge||se!==xt||ue!==Tt)&&(e.stencilFunc(Ge,xt,Tt),k=Ge,se=xt,ue=Tt)},setOp:function(Ge,xt,Tt){(J!==Ge||Te!==xt||ve!==Tt)&&(e.stencilOp(Ge,xt,Tt),J=Ge,Te=xt,ve=Tt)},setLocked:function(Ge){E=Ge},setClear:function(Ge){qe!==Ge&&(e.clearStencil(Ge),qe=Ge)},reset:function(){E=!1,oe=null,k=null,se=null,ue=null,J=null,Te=null,ve=null,qe=null}}}const o=new t,d=new i,g=new l,R=new WeakMap,T=new WeakMap;let H={},I={},p={},M=new WeakMap,N=[],W=null,f=!1,s=null,L=null,z=null,h=null,S=null,m=null,w=null,c=new et(0,0,0),_=0,D=!1,F=null,G=null,q=null,P=null,Y=null;const Q=e.getParameter(e.MAX_COMBINED_TEXTURE_IMAGE_UNITS);let K=!1,ne=0;const Z=e.getParameter(e.VERSION);Z.indexOf("WebGL")!==-1?(ne=parseFloat(/^WebGL (\d)/.exec(Z)[1]),K=ne>=1):Z.indexOf("OpenGL ES")!==-1&&(ne=parseFloat(/^OpenGL ES (\d)/.exec(Z)[1]),K=ne>=2);let j=null,ee={};const be=e.getParameter(e.SCISSOR_BOX),Re=e.getParameter(e.VIEWPORT),it=new _t().fromArray(be),ke=new _t().fromArray(Re);function ze(E,oe,k,se){const ue=new Uint8Array(4),J=e.createTexture();e.bindTexture(E,J),e.texParameteri(E,e.TEXTURE_MIN_FILTER,e.NEAREST),e.texParameteri(E,e.TEXTURE_MAG_FILTER,e.NEAREST);for(let Te=0;Te<k;Te++)E===e.TEXTURE_3D||E===e.TEXTURE_2D_ARRAY?e.texImage3D(oe,0,e.RGBA,1,1,se,0,e.RGBA,e.UNSIGNED_BYTE,ue):e.texImage2D(oe+Te,0,e.RGBA,1,1,0,e.RGBA,e.UNSIGNED_BYTE,ue);return J}const V={};V[e.TEXTURE_2D]=ze(e.TEXTURE_2D,e.TEXTURE_2D,1),V[e.TEXTURE_CUBE_MAP]=ze(e.TEXTURE_CUBE_MAP,e.TEXTURE_CUBE_MAP_POSITIVE_X,6),V[e.TEXTURE_2D_ARRAY]=ze(e.TEXTURE_2D_ARRAY,e.TEXTURE_2D_ARRAY,1,1),V[e.TEXTURE_3D]=ze(e.TEXTURE_3D,e.TEXTURE_3D,1,1),o.setClear(0,0,0,1),d.setClear(1),g.setClear(0),$(e.DEPTH_TEST),d.setFunc(ci),Ie(!1),je(di),$(e.CULL_FACE),Be(wt);function $(E){H[E]!==!0&&(e.enable(E),H[E]=!0)}function Ee(E){H[E]!==!1&&(e.disable(E),H[E]=!1)}function Ue(E,oe){return p[E]!==oe?(e.bindFramebuffer(E,oe),p[E]=oe,E===e.DRAW_FRAMEBUFFER&&(p[e.FRAMEBUFFER]=oe),E===e.FRAMEBUFFER&&(p[e.DRAW_FRAMEBUFFER]=oe),!0):!1}function me(E,oe){let k=N,se=!1;if(E){k=M.get(oe),k===void 0&&(k=[],M.set(oe,k));const ue=E.textures;if(k.length!==ue.length||k[0]!==e.COLOR_ATTACHMENT0){for(let J=0,Te=ue.length;J<Te;J++)k[J]=e.COLOR_ATTACHMENT0+J;k.length=ue.length,se=!0}}else k[0]!==e.BACK&&(k[0]=e.BACK,se=!0);se&&e.drawBuffers(k)}function ye(E){return W!==E?(e.useProgram(E),W=E,!0):!1}const st={[tn]:e.FUNC_ADD,[ra]:e.FUNC_SUBTRACT,[ia]:e.FUNC_REVERSE_SUBTRACT};st[vo]=e.MIN,st[So]=e.MAX;const we={[Sa]:e.ZERO,[va]:e.ONE,[ga]:e.SRC_COLOR,[_a]:e.SRC_ALPHA,[ma]:e.SRC_ALPHA_SATURATE,[ha]:e.DST_COLOR,[pa]:e.DST_ALPHA,[ua]:e.ONE_MINUS_SRC_COLOR,[da]:e.ONE_MINUS_SRC_ALPHA,[fa]:e.ONE_MINUS_DST_COLOR,[ca]:e.ONE_MINUS_DST_ALPHA,[la]:e.CONSTANT_COLOR,[sa]:e.ONE_MINUS_CONSTANT_COLOR,[oa]:e.CONSTANT_ALPHA,[aa]:e.ONE_MINUS_CONSTANT_ALPHA};function Be(E,oe,k,se,ue,J,Te,ve,qe,Ge){if(E===wt){f===!0&&(Ee(e.BLEND),f=!1);return}if(f===!1&&($(e.BLEND),f=!0),E!==Za){if(E!==s||Ge!==D){if((L!==tn||S!==tn)&&(e.blendEquation(e.FUNC_ADD),L=tn,S=tn),Ge)switch(E){case gn:e.blendFuncSeparate(e.ONE,e.ONE_MINUS_SRC_ALPHA,e.ONE,e.ONE_MINUS_SRC_ALPHA);break;case hi:e.blendFunc(e.ONE,e.ONE);break;case pi:e.blendFuncSeparate(e.ZERO,e.ONE_MINUS_SRC_COLOR,e.ZERO,e.ONE);break;case ui:e.blendFuncSeparate(e.DST_COLOR,e.ONE_MINUS_SRC_ALPHA,e.ZERO,e.ONE);break;default:Je("WebGLState: Invalid blending: ",E);break}else switch(E){case gn:e.blendFuncSeparate(e.SRC_ALPHA,e.ONE_MINUS_SRC_ALPHA,e.ONE,e.ONE_MINUS_SRC_ALPHA);break;case hi:e.blendFuncSeparate(e.SRC_ALPHA,e.ONE,e.ONE,e.ONE);break;case pi:Je("WebGLState: SubtractiveBlending requires material.premultipliedAlpha = true");break;case ui:Je("WebGLState: MultiplyBlending requires material.premultipliedAlpha = true");break;default:Je("WebGLState: Invalid blending: ",E);break}z=null,h=null,m=null,w=null,c.set(0,0,0),_=0,s=E,D=Ge}return}ue=ue||oe,J=J||k,Te=Te||se,(oe!==L||ue!==S)&&(e.blendEquationSeparate(st[oe],st[ue]),L=oe,S=ue),(k!==z||se!==h||J!==m||Te!==w)&&(e.blendFuncSeparate(we[k],we[se],we[J],we[Te]),z=k,h=se,m=J,w=Te),(ve.equals(c)===!1||qe!==_)&&(e.blendColor(ve.r,ve.g,ve.b,qe),c.copy(ve),_=qe),s=E,D=!1}function Ke(E,oe){E.side===Lt?Ee(e.CULL_FACE):$(e.CULL_FACE);let k=E.side===St;oe&&(k=!k),Ie(k),E.blending===gn&&E.transparent===!1?Be(wt):Be(E.blending,E.blendEquation,E.blendSrc,E.blendDst,E.blendEquationAlpha,E.blendSrcAlpha,E.blendDstAlpha,E.blendColor,E.blendAlpha,E.premultipliedAlpha),d.setFunc(E.depthFunc),d.setTest(E.depthTest),d.setMask(E.depthWrite),o.setMask(E.colorWrite);const se=E.stencilWrite;g.setTest(se),se&&(g.setMask(E.stencilWriteMask),g.setFunc(E.stencilFunc,E.stencilRef,E.stencilFuncMask),g.setOp(E.stencilFail,E.stencilZFail,E.stencilZPass)),ht(E.polygonOffset,E.polygonOffsetFactor,E.polygonOffsetUnits),E.alphaToCoverage===!0?$(e.SAMPLE_ALPHA_TO_COVERAGE):Ee(e.SAMPLE_ALPHA_TO_COVERAGE)}function Ie(E){F!==E&&(E?e.frontFace(e.CW):e.frontFace(e.CCW),F=E)}function je(E){E!==Ka?($(e.CULL_FACE),E!==G&&(E===di?e.cullFace(e.BACK):E===qa?e.cullFace(e.FRONT):e.cullFace(e.FRONT_AND_BACK))):Ee(e.CULL_FACE),G=E}function ft(E){E!==q&&(K&&e.lineWidth(E),q=E)}function ht(E,oe,k){E?($(e.POLYGON_OFFSET_FILL),(P!==oe||Y!==k)&&(P=oe,Y=k,d.getReversed()&&(oe=-oe),e.polygonOffset(oe,k))):Ee(e.POLYGON_OFFSET_FILL)}function tt(E){E?$(e.SCISSOR_TEST):Ee(e.SCISSOR_TEST)}function at(E){E===void 0&&(E=e.TEXTURE0+Q-1),j!==E&&(e.activeTexture(E),j=E)}function x(E,oe,k){k===void 0&&(j===null?k=e.TEXTURE0+Q-1:k=j);let se=ee[k];se===void 0&&(se={type:void 0,texture:void 0},ee[k]=se),(se.type!==E||se.texture!==oe)&&(j!==k&&(e.activeTexture(k),j=k),e.bindTexture(E,oe||V[E]),se.type=E,se.texture=oe)}function dt(){const E=ee[j];E!==void 0&&E.type!==void 0&&(e.bindTexture(E.type,null),E.type=void 0,E.texture=void 0)}function Ve(){try{e.compressedTexImage2D(...arguments)}catch(E){Je("WebGLState:",E)}}function u(){try{e.compressedTexImage3D(...arguments)}catch(E){Je("WebGLState:",E)}}function r(){try{e.texSubImage2D(...arguments)}catch(E){Je("WebGLState:",E)}}function A(){try{e.texSubImage3D(...arguments)}catch(E){Je("WebGLState:",E)}}function U(){try{e.compressedTexSubImage2D(...arguments)}catch(E){Je("WebGLState:",E)}}function O(){try{e.compressedTexSubImage3D(...arguments)}catch(E){Je("WebGLState:",E)}}function te(){try{e.texStorage2D(...arguments)}catch(E){Je("WebGLState:",E)}}function ie(){try{e.texStorage3D(...arguments)}catch(E){Je("WebGLState:",E)}}function B(){try{e.texImage2D(...arguments)}catch(E){Je("WebGLState:",E)}}function X(){try{e.texImage3D(...arguments)}catch(E){Je("WebGLState:",E)}}function re(E){return I[E]!==void 0?I[E]:e.getParameter(E)}function xe(E,oe){I[E]!==oe&&(e.pixelStorei(E,oe),I[E]=oe)}function le(E){it.equals(E)===!1&&(e.scissor(E.x,E.y,E.z,E.w),it.copy(E))}function ae(E){ke.equals(E)===!1&&(e.viewport(E.x,E.y,E.z,E.w),ke.copy(E))}function Me(E,oe){let k=T.get(oe);k===void 0&&(k=new WeakMap,T.set(oe,k));let se=k.get(E);se===void 0&&(se=e.getUniformBlockIndex(oe,E.name),k.set(E,se))}function Ae(E,oe){const se=T.get(oe).get(E);R.get(oe)!==se&&(e.uniformBlockBinding(oe,se,E.__bindingPointIndex),R.set(oe,se))}function Ce(){e.disable(e.BLEND),e.disable(e.CULL_FACE),e.disable(e.DEPTH_TEST),e.disable(e.POLYGON_OFFSET_FILL),e.disable(e.SCISSOR_TEST),e.disable(e.STENCIL_TEST),e.disable(e.SAMPLE_ALPHA_TO_COVERAGE),e.blendEquation(e.FUNC_ADD),e.blendFunc(e.ONE,e.ZERO),e.blendFuncSeparate(e.ONE,e.ZERO,e.ONE,e.ZERO),e.blendColor(0,0,0,0),e.colorMask(!0,!0,!0,!0),e.clearColor(0,0,0,0),e.depthMask(!0),e.depthFunc(e.LESS),d.setReversed(!1),e.clearDepth(1),e.stencilMask(4294967295),e.stencilFunc(e.ALWAYS,0,4294967295),e.stencilOp(e.KEEP,e.KEEP,e.KEEP),e.clearStencil(0),e.cullFace(e.BACK),e.frontFace(e.CCW),e.polygonOffset(0,0),e.activeTexture(e.TEXTURE0),e.bindFramebuffer(e.FRAMEBUFFER,null),e.bindFramebuffer(e.DRAW_FRAMEBUFFER,null),e.bindFramebuffer(e.READ_FRAMEBUFFER,null),e.useProgram(null),e.lineWidth(1),e.scissor(0,0,e.canvas.width,e.canvas.height),e.viewport(0,0,e.canvas.width,e.canvas.height),e.pixelStorei(e.PACK_ALIGNMENT,4),e.pixelStorei(e.UNPACK_ALIGNMENT,4),e.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,!1),e.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,!1),e.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,e.BROWSER_DEFAULT_WEBGL),e.pixelStorei(e.PACK_ROW_LENGTH,0),e.pixelStorei(e.PACK_SKIP_PIXELS,0),e.pixelStorei(e.PACK_SKIP_ROWS,0),e.pixelStorei(e.UNPACK_ROW_LENGTH,0),e.pixelStorei(e.UNPACK_IMAGE_HEIGHT,0),e.pixelStorei(e.UNPACK_SKIP_PIXELS,0),e.pixelStorei(e.UNPACK_SKIP_ROWS,0),e.pixelStorei(e.UNPACK_SKIP_IMAGES,0),H={},I={},j=null,ee={},p={},M=new WeakMap,N=[],W=null,f=!1,s=null,L=null,z=null,h=null,S=null,m=null,w=null,c=new et(0,0,0),_=0,D=!1,F=null,G=null,q=null,P=null,Y=null,it.set(0,0,e.canvas.width,e.canvas.height),ke.set(0,0,e.canvas.width,e.canvas.height),o.reset(),d.reset(),g.reset()}return{buffers:{color:o,depth:d,stencil:g},enable:$,disable:Ee,bindFramebuffer:Ue,drawBuffers:me,useProgram:ye,setBlending:Be,setMaterial:Ke,setFlipSided:Ie,setCullFace:je,setLineWidth:ft,setPolygonOffset:ht,setScissorTest:tt,activeTexture:at,bindTexture:x,unbindTexture:dt,compressedTexImage2D:Ve,compressedTexImage3D:u,texImage2D:B,texImage3D:X,pixelStorei:xe,getParameter:re,updateUBOMapping:Me,uniformBlockBinding:Ae,texStorage2D:te,texStorage3D:ie,texSubImage2D:r,texSubImage3D:A,compressedTexSubImage2D:U,compressedTexSubImage3D:O,scissor:le,viewport:ae,reset:Ce}}function od(e,n,t,i,l,o,d){const g=n.has("WEBGL_multisampled_render_to_texture")?n.get("WEBGL_multisampled_render_to_texture"):null,R=typeof navigator>"u"?!1:/OculusBrowser/g.test(navigator.userAgent),T=new gt,H=new WeakMap,I=new Set;let p;const M=new WeakMap;let N=!1;try{N=typeof OffscreenCanvas<"u"&&new OffscreenCanvas(1,1).getContext("2d")!==null}catch{}function W(u,r){return N?new OffscreenCanvas(u,r):fo("canvas")}function f(u,r,A){let U=1;const O=Ve(u);if((O.width>A||O.height>A)&&(U=A/Math.max(O.width,O.height)),U<1)if(typeof HTMLImageElement<"u"&&u instanceof HTMLImageElement||typeof HTMLCanvasElement<"u"&&u instanceof HTMLCanvasElement||typeof ImageBitmap<"u"&&u instanceof ImageBitmap||typeof VideoFrame<"u"&&u instanceof VideoFrame){const te=Math.floor(U*O.width),ie=Math.floor(U*O.height);p===void 0&&(p=W(te,ie));const B=r?W(te,ie):p;return B.width=te,B.height=ie,B.getContext("2d").drawImage(u,0,0,te,ie),We("WebGLRenderer: Texture has been resized from ("+O.width+"x"+O.height+") to ("+te+"x"+ie+")."),B}else return"data"in u&&We("WebGLRenderer: Image in DataTexture is too big ("+O.width+"x"+O.height+")."),u;return u}function s(u){return u.generateMipmaps}function L(u){e.generateMipmap(u)}function z(u){return u.isWebGLCubeRenderTarget?e.TEXTURE_CUBE_MAP:u.isWebGL3DRenderTarget?e.TEXTURE_3D:u.isWebGLArrayRenderTarget||u.isCompressedArrayTexture?e.TEXTURE_2D_ARRAY:e.TEXTURE_2D}function h(u,r,A,U,O,te=!1){if(u!==null){if(e[u]!==void 0)return e[u];We("WebGLRenderer: Attempt to use non-existing WebGL internal format '"+u+"'")}let ie;U&&(ie=n.get("EXT_texture_norm16"),ie||We("WebGLRenderer: Unable to use normalized textures without EXT_texture_norm16 extension"));let B=r;if(r===e.RED&&(A===e.FLOAT&&(B=e.R32F),A===e.HALF_FLOAT&&(B=e.R16F),A===e.UNSIGNED_BYTE&&(B=e.R8),A===e.UNSIGNED_SHORT&&ie&&(B=ie.R16_EXT),A===e.SHORT&&ie&&(B=ie.R16_SNORM_EXT)),r===e.RED_INTEGER&&(A===e.UNSIGNED_BYTE&&(B=e.R8UI),A===e.UNSIGNED_SHORT&&(B=e.R16UI),A===e.UNSIGNED_INT&&(B=e.R32UI),A===e.BYTE&&(B=e.R8I),A===e.SHORT&&(B=e.R16I),A===e.INT&&(B=e.R32I)),r===e.RG&&(A===e.FLOAT&&(B=e.RG32F),A===e.HALF_FLOAT&&(B=e.RG16F),A===e.UNSIGNED_BYTE&&(B=e.RG8),A===e.UNSIGNED_SHORT&&ie&&(B=ie.RG16_EXT),A===e.SHORT&&ie&&(B=ie.RG16_SNORM_EXT)),r===e.RG_INTEGER&&(A===e.UNSIGNED_BYTE&&(B=e.RG8UI),A===e.UNSIGNED_SHORT&&(B=e.RG16UI),A===e.UNSIGNED_INT&&(B=e.RG32UI),A===e.BYTE&&(B=e.RG8I),A===e.SHORT&&(B=e.RG16I),A===e.INT&&(B=e.RG32I)),r===e.RGB_INTEGER&&(A===e.UNSIGNED_BYTE&&(B=e.RGB8UI),A===e.UNSIGNED_SHORT&&(B=e.RGB16UI),A===e.UNSIGNED_INT&&(B=e.RGB32UI),A===e.BYTE&&(B=e.RGB8I),A===e.SHORT&&(B=e.RGB16I),A===e.INT&&(B=e.RGB32I)),r===e.RGBA_INTEGER&&(A===e.UNSIGNED_BYTE&&(B=e.RGBA8UI),A===e.UNSIGNED_SHORT&&(B=e.RGBA16UI),A===e.UNSIGNED_INT&&(B=e.RGBA32UI),A===e.BYTE&&(B=e.RGBA8I),A===e.SHORT&&(B=e.RGBA16I),A===e.INT&&(B=e.RGBA32I)),r===e.RGB&&(A===e.UNSIGNED_SHORT&&ie&&(B=ie.RGB16_EXT),A===e.SHORT&&ie&&(B=ie.RGB16_SNORM_EXT),A===e.UNSIGNED_INT_5_9_9_9_REV&&(B=e.RGB9_E5),A===e.UNSIGNED_INT_10F_11F_11F_REV&&(B=e.R11F_G11F_B10F)),r===e.RGBA){const X=te?Lr:nt.getTransfer(O);A===e.FLOAT&&(B=e.RGBA32F),A===e.HALF_FLOAT&&(B=e.RGBA16F),A===e.UNSIGNED_BYTE&&(B=X===$e?e.SRGB8_ALPHA8:e.RGBA8),A===e.UNSIGNED_SHORT&&ie&&(B=ie.RGBA16_EXT),A===e.SHORT&&ie&&(B=ie.RGBA16_SNORM_EXT),A===e.UNSIGNED_SHORT_4_4_4_4&&(B=e.RGBA4),A===e.UNSIGNED_SHORT_5_5_5_1&&(B=e.RGB5_A1)}return(B===e.R16F||B===e.R32F||B===e.RG16F||B===e.RG32F||B===e.RGBA16F||B===e.RGBA32F)&&n.get("EXT_color_buffer_float"),B}function S(u,r){let A;return u?r===null||r===Wt||r===ln?A=e.DEPTH24_STENCIL8:r===Bt?A=e.DEPTH32F_STENCIL8:r===En&&(A=e.DEPTH24_STENCIL8,We("DepthTexture: 16 bit depth attachment is not supported with stencil. Using 24-bit attachment.")):r===null||r===Wt||r===ln?A=e.DEPTH_COMPONENT24:r===Bt?A=e.DEPTH_COMPONENT32F:r===En&&(A=e.DEPTH_COMPONENT16),A}function m(u,r){return s(u)===!0||u.isFramebufferTexture&&u.minFilter!==Vt&&u.minFilter!==vt?Math.log2(Math.max(r.width,r.height))+1:u.mipmaps!==void 0&&u.mipmaps.length>0?u.mipmaps.length:u.isCompressedTexture&&Array.isArray(u.image)?r.mipmaps.length:1}function w(u){const r=u.target;r.removeEventListener("dispose",w),_(r),r.isVideoTexture&&H.delete(r),r.isHTMLTexture&&I.delete(r)}function c(u){const r=u.target;r.removeEventListener("dispose",c),F(r)}function _(u){const r=i.get(u);if(r.__webglInit===void 0)return;const A=u.source,U=M.get(A);if(U){const O=U[r.__cacheKey];O.usedTimes--,O.usedTimes===0&&D(u),Object.keys(U).length===0&&M.delete(A)}i.remove(u)}function D(u){const r=i.get(u);e.deleteTexture(r.__webglTexture);const A=u.source,U=M.get(A);delete U[r.__cacheKey],d.memory.textures--}function F(u){const r=i.get(u);if(u.depthTexture&&(u.depthTexture.dispose(),i.remove(u.depthTexture)),u.isWebGLCubeRenderTarget)for(let U=0;U<6;U++){if(Array.isArray(r.__webglFramebuffer[U]))for(let O=0;O<r.__webglFramebuffer[U].length;O++)e.deleteFramebuffer(r.__webglFramebuffer[U][O]);else e.deleteFramebuffer(r.__webglFramebuffer[U]);r.__webglDepthbuffer&&e.deleteRenderbuffer(r.__webglDepthbuffer[U])}else{if(Array.isArray(r.__webglFramebuffer))for(let U=0;U<r.__webglFramebuffer.length;U++)e.deleteFramebuffer(r.__webglFramebuffer[U]);else e.deleteFramebuffer(r.__webglFramebuffer);if(r.__webglDepthbuffer&&e.deleteRenderbuffer(r.__webglDepthbuffer),r.__webglMultisampledFramebuffer&&e.deleteFramebuffer(r.__webglMultisampledFramebuffer),r.__webglColorRenderbuffer)for(let U=0;U<r.__webglColorRenderbuffer.length;U++)r.__webglColorRenderbuffer[U]&&e.deleteRenderbuffer(r.__webglColorRenderbuffer[U]);r.__webglDepthRenderbuffer&&e.deleteRenderbuffer(r.__webglDepthRenderbuffer)}const A=u.textures;for(let U=0,O=A.length;U<O;U++){const te=i.get(A[U]);te.__webglTexture&&(e.deleteTexture(te.__webglTexture),d.memory.textures--),i.remove(A[U])}i.remove(u)}let G=0;function q(){G=0}function P(){return G}function Y(u){G=u}function Q(){const u=G;return u>=l.maxTextures&&We("WebGLTextures: Trying to use "+(u+1)+" texture units while this GPU supports only "+l.maxTextures),G+=1,u}function K(u){const r=[];return r.push(u.wrapS),r.push(u.wrapT),r.push(u.wrapR||0),r.push(u.magFilter),r.push(u.minFilter),r.push(u.anisotropy),r.push(u.internalFormat),r.push(u.format),r.push(u.type),r.push(u.generateMipmaps),r.push(u.premultiplyAlpha),r.push(u.flipY),r.push(u.unpackAlignment),r.push(u.colorSpace),r.join()}function ne(u,r){const A=i.get(u);if(u.isVideoTexture&&x(u),u.isRenderTargetTexture===!1&&u.isExternalTexture!==!0&&u.version>0&&A.__version!==u.version){const U=u.image;if(U===null)We("WebGLRenderer: Texture marked for update but no image data found.");else if(U.complete===!1)We("WebGLRenderer: Texture marked for update but image is incomplete");else{Ee(A,u,r);return}}else u.isExternalTexture&&(A.__webglTexture=u.sourceTexture?u.sourceTexture:null);t.bindTexture(e.TEXTURE_2D,A.__webglTexture,e.TEXTURE0+r)}function Z(u,r){const A=i.get(u);if(u.isRenderTargetTexture===!1&&u.version>0&&A.__version!==u.version){Ee(A,u,r);return}else u.isExternalTexture&&(A.__webglTexture=u.sourceTexture?u.sourceTexture:null);t.bindTexture(e.TEXTURE_2D_ARRAY,A.__webglTexture,e.TEXTURE0+r)}function j(u,r){const A=i.get(u);if(u.isRenderTargetTexture===!1&&u.version>0&&A.__version!==u.version){Ee(A,u,r);return}t.bindTexture(e.TEXTURE_3D,A.__webglTexture,e.TEXTURE0+r)}function ee(u,r){const A=i.get(u);if(u.isCubeDepthTexture!==!0&&u.version>0&&A.__version!==u.version){Ue(A,u,r);return}t.bindTexture(e.TEXTURE_CUBE_MAP,A.__webglTexture,e.TEXTURE0+r)}const be={[xa]:e.REPEAT,[Vn]:e.CLAMP_TO_EDGE,[Ea]:e.MIRRORED_REPEAT},Re={[Vt]:e.NEAREST,[Ma]:e.NEAREST_MIPMAP_NEAREST,[un]:e.NEAREST_MIPMAP_LINEAR,[vt]:e.LINEAR,[Cn]:e.LINEAR_MIPMAP_NEAREST,[Kt]:e.LINEAR_MIPMAP_LINEAR},it={[Pa]:e.NEVER,[Ca]:e.ALWAYS,[ba]:e.LESS,[Zn]:e.LEQUAL,[Ra]:e.EQUAL,[qn]:e.GEQUAL,[Aa]:e.GREATER,[Ta]:e.NOTEQUAL};function ke(u,r){if(r.type===Bt&&n.has("OES_texture_float_linear")===!1&&(r.magFilter===vt||r.magFilter===Cn||r.magFilter===un||r.magFilter===Kt||r.minFilter===vt||r.minFilter===Cn||r.minFilter===un||r.minFilter===Kt)&&We("WebGLRenderer: Unable to use linear filtering with floating point textures. OES_texture_float_linear not supported on this device."),e.texParameteri(u,e.TEXTURE_WRAP_S,be[r.wrapS]),e.texParameteri(u,e.TEXTURE_WRAP_T,be[r.wrapT]),(u===e.TEXTURE_3D||u===e.TEXTURE_2D_ARRAY)&&e.texParameteri(u,e.TEXTURE_WRAP_R,be[r.wrapR]),e.texParameteri(u,e.TEXTURE_MAG_FILTER,Re[r.magFilter]),e.texParameteri(u,e.TEXTURE_MIN_FILTER,Re[r.minFilter]),r.compareFunction&&(e.texParameteri(u,e.TEXTURE_COMPARE_MODE,e.COMPARE_REF_TO_TEXTURE),e.texParameteri(u,e.TEXTURE_COMPARE_FUNC,it[r.compareFunction])),n.has("EXT_texture_filter_anisotropic")===!0){if(r.magFilter===Vt||r.minFilter!==un&&r.minFilter!==Kt||r.type===Bt&&n.has("OES_texture_float_linear")===!1)return;if(r.anisotropy>1||i.get(r).__currentAnisotropy){const A=n.get("EXT_texture_filter_anisotropic");e.texParameterf(u,A.TEXTURE_MAX_ANISOTROPY_EXT,Math.min(r.anisotropy,l.getMaxAnisotropy())),i.get(r).__currentAnisotropy=r.anisotropy}}}function ze(u,r){let A=!1;u.__webglInit===void 0&&(u.__webglInit=!0,r.addEventListener("dispose",w));const U=r.source;let O=M.get(U);O===void 0&&(O={},M.set(U,O));const te=K(r);if(te!==u.__cacheKey){O[te]===void 0&&(O[te]={texture:e.createTexture(),usedTimes:0},d.memory.textures++,A=!0),O[te].usedTimes++;const ie=O[u.__cacheKey];ie!==void 0&&(O[u.__cacheKey].usedTimes--,ie.usedTimes===0&&D(r)),u.__cacheKey=te,u.__webglTexture=O[te].texture}return A}function V(u,r,A){return Math.floor(Math.floor(u/A)/r)}function $(u,r,A,U){const te=u.updateRanges;if(te.length===0)t.texSubImage2D(e.TEXTURE_2D,0,0,0,r.width,r.height,A,U,r.data);else{te.sort((xe,le)=>xe.start-le.start);let ie=0;for(let xe=1;xe<te.length;xe++){const le=te[ie],ae=te[xe],Me=le.start+le.count,Ae=V(ae.start,r.width,4),Ce=V(le.start,r.width,4);ae.start<=Me+1&&Ae===Ce&&V(ae.start+ae.count-1,r.width,4)===Ae?le.count=Math.max(le.count,ae.start+ae.count-le.start):(++ie,te[ie]=ae)}te.length=ie+1;const B=t.getParameter(e.UNPACK_ROW_LENGTH),X=t.getParameter(e.UNPACK_SKIP_PIXELS),re=t.getParameter(e.UNPACK_SKIP_ROWS);t.pixelStorei(e.UNPACK_ROW_LENGTH,r.width);for(let xe=0,le=te.length;xe<le;xe++){const ae=te[xe],Me=Math.floor(ae.start/4),Ae=Math.ceil(ae.count/4),Ce=Me%r.width,E=Math.floor(Me/r.width),oe=Ae,k=1;t.pixelStorei(e.UNPACK_SKIP_PIXELS,Ce),t.pixelStorei(e.UNPACK_SKIP_ROWS,E),t.texSubImage2D(e.TEXTURE_2D,0,Ce,E,oe,k,A,U,r.data)}u.clearUpdateRanges(),t.pixelStorei(e.UNPACK_ROW_LENGTH,B),t.pixelStorei(e.UNPACK_SKIP_PIXELS,X),t.pixelStorei(e.UNPACK_SKIP_ROWS,re)}}function Ee(u,r,A){let U=e.TEXTURE_2D;(r.isDataArrayTexture||r.isCompressedArrayTexture)&&(U=e.TEXTURE_2D_ARRAY),r.isData3DTexture&&(U=e.TEXTURE_3D);const O=ze(u,r),te=r.source;t.bindTexture(U,u.__webglTexture,e.TEXTURE0+A);const ie=i.get(te);if(te.version!==ie.__version||O===!0){if(t.activeTexture(e.TEXTURE0+A),(typeof ImageBitmap<"u"&&r.image instanceof ImageBitmap)===!1){const k=nt.getPrimaries(nt.workingColorSpace),se=r.colorSpace===Yt?null:nt.getPrimaries(r.colorSpace),ue=r.colorSpace===Yt||k===se?e.NONE:e.BROWSER_DEFAULT_WEBGL;t.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,r.flipY),t.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,r.premultiplyAlpha),t.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,ue)}t.pixelStorei(e.UNPACK_ALIGNMENT,r.unpackAlignment);let X=f(r.image,!1,l.maxTextureSize);X=dt(r,X);const re=o.convert(r.format,r.colorSpace),xe=o.convert(r.type);let le=h(r.internalFormat,re,xe,r.normalized,r.colorSpace,r.isVideoTexture);ke(U,r);let ae;const Me=r.mipmaps,Ae=r.isVideoTexture!==!0,Ce=ie.__version===void 0||O===!0,E=te.dataReady,oe=m(r,X);if(r.isDepthTexture)le=S(r.format===qt,r.type),Ce&&(Ae?t.texStorage2D(e.TEXTURE_2D,1,le,X.width,X.height):t.texImage2D(e.TEXTURE_2D,0,le,X.width,X.height,0,re,xe,null));else if(r.isDataTexture)if(Me.length>0){Ae&&Ce&&t.texStorage2D(e.TEXTURE_2D,oe,le,Me[0].width,Me[0].height);for(let k=0,se=Me.length;k<se;k++)ae=Me[k],Ae?E&&t.texSubImage2D(e.TEXTURE_2D,k,0,0,ae.width,ae.height,re,xe,ae.data):t.texImage2D(e.TEXTURE_2D,k,le,ae.width,ae.height,0,re,xe,ae.data);r.generateMipmaps=!1}else Ae?(Ce&&t.texStorage2D(e.TEXTURE_2D,oe,le,X.width,X.height),E&&$(r,X,re,xe)):t.texImage2D(e.TEXTURE_2D,0,le,X.width,X.height,0,re,xe,X.data);else if(r.isCompressedTexture)if(r.isCompressedArrayTexture){Ae&&Ce&&t.texStorage3D(e.TEXTURE_2D_ARRAY,oe,le,Me[0].width,Me[0].height,X.depth);for(let k=0,se=Me.length;k<se;k++)if(ae=Me[k],r.format!==Ut)if(re!==null)if(Ae){if(E)if(r.layerUpdates.size>0){const ue=Yi(ae.width,ae.height,r.format,r.type);for(const J of r.layerUpdates){const Te=ae.data.subarray(J*ue/ae.data.BYTES_PER_ELEMENT,(J+1)*ue/ae.data.BYTES_PER_ELEMENT);t.compressedTexSubImage3D(e.TEXTURE_2D_ARRAY,k,0,0,J,ae.width,ae.height,1,re,Te)}}else t.compressedTexSubImage3D(e.TEXTURE_2D_ARRAY,k,0,0,0,ae.width,ae.height,X.depth,re,ae.data)}else t.compressedTexImage3D(e.TEXTURE_2D_ARRAY,k,le,ae.width,ae.height,X.depth,0,ae.data,0,0);else We("WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()");else Ae?E&&t.texSubImage3D(e.TEXTURE_2D_ARRAY,k,0,0,0,ae.width,ae.height,X.depth,re,xe,ae.data):t.texImage3D(e.TEXTURE_2D_ARRAY,k,le,ae.width,ae.height,X.depth,0,re,xe,ae.data);r.layerUpdates.size>0&&r.clearLayerUpdates()}else{Ae&&Ce&&t.texStorage2D(e.TEXTURE_2D,oe,le,Me[0].width,Me[0].height);for(let k=0,se=Me.length;k<se;k++)ae=Me[k],r.format!==Ut?re!==null?Ae?E&&t.compressedTexSubImage2D(e.TEXTURE_2D,k,0,0,ae.width,ae.height,re,ae.data):t.compressedTexImage2D(e.TEXTURE_2D,k,le,ae.width,ae.height,0,ae.data):We("WebGLRenderer: Attempt to load unsupported compressed texture format in .uploadTexture()"):Ae?E&&t.texSubImage2D(e.TEXTURE_2D,k,0,0,ae.width,ae.height,re,xe,ae.data):t.texImage2D(e.TEXTURE_2D,k,le,ae.width,ae.height,0,re,xe,ae.data)}else if(r.isDataArrayTexture)if(Ae){if(Ce&&t.texStorage3D(e.TEXTURE_2D_ARRAY,oe,le,X.width,X.height,X.depth),E)if(r.layerUpdates.size>0){const k=Yi(X.width,X.height,r.format,r.type);for(const se of r.layerUpdates){const ue=X.data.subarray(se*k/X.data.BYTES_PER_ELEMENT,(se+1)*k/X.data.BYTES_PER_ELEMENT);t.texSubImage3D(e.TEXTURE_2D_ARRAY,0,0,0,se,X.width,X.height,1,re,xe,ue)}r.clearLayerUpdates()}else t.texSubImage3D(e.TEXTURE_2D_ARRAY,0,0,0,0,X.width,X.height,X.depth,re,xe,X.data)}else t.texImage3D(e.TEXTURE_2D_ARRAY,0,le,X.width,X.height,X.depth,0,re,xe,X.data);else if(r.isData3DTexture)Ae?(Ce&&t.texStorage3D(e.TEXTURE_3D,oe,le,X.width,X.height,X.depth),E&&t.texSubImage3D(e.TEXTURE_3D,0,0,0,0,X.width,X.height,X.depth,re,xe,X.data)):t.texImage3D(e.TEXTURE_3D,0,le,X.width,X.height,X.depth,0,re,xe,X.data);else if(r.isFramebufferTexture){if(Ce)if(Ae)t.texStorage2D(e.TEXTURE_2D,oe,le,X.width,X.height);else{let k=X.width,se=X.height;for(let ue=0;ue<oe;ue++)t.texImage2D(e.TEXTURE_2D,ue,le,k,se,0,re,xe,null),k>>=1,se>>=1}}else if(r.isHTMLTexture){if("texElementImage2D"in e){const k=e.canvas;if(k.hasAttribute("layoutsubtree")||k.setAttribute("layoutsubtree","true"),X.parentNode!==k){k.appendChild(X),I.add(r),k.onpaint=se=>{const ue=se.changedElements;for(const J of I)ue.includes(J.image)&&(J.needsUpdate=!0)},k.requestPaint();return}if(e.texElementImage2D.length===3)e.texElementImage2D(e.TEXTURE_2D,e.RGBA8,X);else{const ue=e.RGBA,J=e.RGBA,Te=e.UNSIGNED_BYTE;e.texElementImage2D(e.TEXTURE_2D,0,ue,J,Te,X)}e.texParameteri(e.TEXTURE_2D,e.TEXTURE_MIN_FILTER,e.LINEAR),e.texParameteri(e.TEXTURE_2D,e.TEXTURE_WRAP_S,e.CLAMP_TO_EDGE),e.texParameteri(e.TEXTURE_2D,e.TEXTURE_WRAP_T,e.CLAMP_TO_EDGE)}}else if(Me.length>0){if(Ae&&Ce){const k=Ve(Me[0]);t.texStorage2D(e.TEXTURE_2D,oe,le,k.width,k.height)}for(let k=0,se=Me.length;k<se;k++)ae=Me[k],Ae?E&&t.texSubImage2D(e.TEXTURE_2D,k,0,0,re,xe,ae):t.texImage2D(e.TEXTURE_2D,k,le,re,xe,ae);r.generateMipmaps=!1}else if(Ae){if(Ce){const k=Ve(X);t.texStorage2D(e.TEXTURE_2D,oe,le,k.width,k.height)}E&&t.texSubImage2D(e.TEXTURE_2D,0,0,0,re,xe,X)}else t.texImage2D(e.TEXTURE_2D,0,le,re,xe,X);s(r)&&L(U),ie.__version=te.version,r.onUpdate&&r.onUpdate(r)}u.__version=r.version}function Ue(u,r,A){if(r.image.length!==6)return;const U=ze(u,r),O=r.source;t.bindTexture(e.TEXTURE_CUBE_MAP,u.__webglTexture,e.TEXTURE0+A);const te=i.get(O);if(O.version!==te.__version||U===!0){t.activeTexture(e.TEXTURE0+A);const ie=nt.getPrimaries(nt.workingColorSpace),B=r.colorSpace===Yt?null:nt.getPrimaries(r.colorSpace),X=r.colorSpace===Yt||ie===B?e.NONE:e.BROWSER_DEFAULT_WEBGL;t.pixelStorei(e.UNPACK_FLIP_Y_WEBGL,r.flipY),t.pixelStorei(e.UNPACK_PREMULTIPLY_ALPHA_WEBGL,r.premultiplyAlpha),t.pixelStorei(e.UNPACK_ALIGNMENT,r.unpackAlignment),t.pixelStorei(e.UNPACK_COLORSPACE_CONVERSION_WEBGL,X);const re=r.isCompressedTexture||r.image[0].isCompressedTexture,xe=r.image[0]&&r.image[0].isDataTexture,le=[];for(let J=0;J<6;J++)!re&&!xe?le[J]=f(r.image[J],!0,l.maxCubemapSize):le[J]=xe?r.image[J].image:r.image[J],le[J]=dt(r,le[J]);const ae=le[0],Me=o.convert(r.format,r.colorSpace),Ae=o.convert(r.type),Ce=h(r.internalFormat,Me,Ae,r.normalized,r.colorSpace),E=r.isVideoTexture!==!0,oe=te.__version===void 0||U===!0,k=O.dataReady;let se=m(r,ae);ke(e.TEXTURE_CUBE_MAP,r);let ue;if(re){E&&oe&&t.texStorage2D(e.TEXTURE_CUBE_MAP,se,Ce,ae.width,ae.height);for(let J=0;J<6;J++){ue=le[J].mipmaps;for(let Te=0;Te<ue.length;Te++){const ve=ue[Te];r.format!==Ut?Me!==null?E?k&&t.compressedTexSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te,0,0,ve.width,ve.height,Me,ve.data):t.compressedTexImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te,Ce,ve.width,ve.height,0,ve.data):We("WebGLRenderer: Attempt to load unsupported compressed texture format in .setTextureCube()"):E?k&&t.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te,0,0,ve.width,ve.height,Me,Ae,ve.data):t.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te,Ce,ve.width,ve.height,0,Me,Ae,ve.data)}}}else{if(ue=r.mipmaps,E&&oe){ue.length>0&&se++;const J=Ve(le[0]);t.texStorage2D(e.TEXTURE_CUBE_MAP,se,Ce,J.width,J.height)}for(let J=0;J<6;J++)if(xe){E?k&&t.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,0,0,0,le[J].width,le[J].height,Me,Ae,le[J].data):t.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,0,Ce,le[J].width,le[J].height,0,Me,Ae,le[J].data);for(let Te=0;Te<ue.length;Te++){const qe=ue[Te].image[J].image;E?k&&t.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te+1,0,0,qe.width,qe.height,Me,Ae,qe.data):t.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te+1,Ce,qe.width,qe.height,0,Me,Ae,qe.data)}}else{E?k&&t.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,0,0,0,Me,Ae,le[J]):t.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,0,Ce,Me,Ae,le[J]);for(let Te=0;Te<ue.length;Te++){const ve=ue[Te];E?k&&t.texSubImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te+1,0,0,Me,Ae,ve.image[J]):t.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+J,Te+1,Ce,Me,Ae,ve.image[J])}}}s(r)&&L(e.TEXTURE_CUBE_MAP),te.__version=O.version,r.onUpdate&&r.onUpdate(r)}u.__version=r.version}function me(u,r,A,U,O,te){const ie=o.convert(A.format,A.colorSpace),B=o.convert(A.type),X=h(A.internalFormat,ie,B,A.normalized,A.colorSpace),re=i.get(r),xe=i.get(A);if(xe.__renderTarget=r,!re.__hasExternalTextures){const le=Math.max(1,r.width>>te),ae=Math.max(1,r.height>>te);O===e.TEXTURE_3D||O===e.TEXTURE_2D_ARRAY?t.texImage3D(O,te,X,le,ae,r.depth,0,ie,B,null):t.texImage2D(O,te,X,le,ae,0,ie,B,null)}t.bindFramebuffer(e.FRAMEBUFFER,u),at(r)?g.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,U,O,xe.__webglTexture,0,tt(r)):(O===e.TEXTURE_2D||O>=e.TEXTURE_CUBE_MAP_POSITIVE_X&&O<=e.TEXTURE_CUBE_MAP_NEGATIVE_Z)&&e.framebufferTexture2D(e.FRAMEBUFFER,U,O,xe.__webglTexture,te),t.bindFramebuffer(e.FRAMEBUFFER,null)}function ye(u,r,A){if(e.bindRenderbuffer(e.RENDERBUFFER,u),r.depthBuffer){const U=r.depthTexture,O=U&&U.isDepthTexture?U.type:null,te=S(r.stencilBuffer,O),ie=r.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;at(r)?g.renderbufferStorageMultisampleEXT(e.RENDERBUFFER,tt(r),te,r.width,r.height):A?e.renderbufferStorageMultisample(e.RENDERBUFFER,tt(r),te,r.width,r.height):e.renderbufferStorage(e.RENDERBUFFER,te,r.width,r.height),e.framebufferRenderbuffer(e.FRAMEBUFFER,ie,e.RENDERBUFFER,u)}else{const U=r.textures;for(let O=0;O<U.length;O++){const te=U[O],ie=o.convert(te.format,te.colorSpace),B=o.convert(te.type),X=h(te.internalFormat,ie,B,te.normalized,te.colorSpace);at(r)?g.renderbufferStorageMultisampleEXT(e.RENDERBUFFER,tt(r),X,r.width,r.height):A?e.renderbufferStorageMultisample(e.RENDERBUFFER,tt(r),X,r.width,r.height):e.renderbufferStorage(e.RENDERBUFFER,X,r.width,r.height)}}e.bindRenderbuffer(e.RENDERBUFFER,null)}function st(u,r,A){const U=r.isWebGLCubeRenderTarget===!0;if(t.bindFramebuffer(e.FRAMEBUFFER,u),!(r.depthTexture&&r.depthTexture.isDepthTexture))throw new Error("THREE.WebGLTextures: renderTarget.depthTexture must be an instance of THREE.DepthTexture.");const O=i.get(r.depthTexture);if(O.__renderTarget=r,(!O.__webglTexture||r.depthTexture.image.width!==r.width||r.depthTexture.image.height!==r.height)&&(r.depthTexture.image.width=r.width,r.depthTexture.image.height=r.height,r.depthTexture.needsUpdate=!0),U){if(O.__webglInit===void 0&&(O.__webglInit=!0,r.depthTexture.addEventListener("dispose",w)),O.__webglTexture===void 0){O.__webglTexture=e.createTexture(),t.bindTexture(e.TEXTURE_CUBE_MAP,O.__webglTexture),ke(e.TEXTURE_CUBE_MAP,r.depthTexture);const re=o.convert(r.depthTexture.format),xe=o.convert(r.depthTexture.type);let le;r.depthTexture.format===Jt?le=e.DEPTH_COMPONENT24:r.depthTexture.format===qt&&(le=e.DEPTH24_STENCIL8);for(let ae=0;ae<6;ae++)e.texImage2D(e.TEXTURE_CUBE_MAP_POSITIVE_X+ae,0,le,r.width,r.height,0,re,xe,null)}}else ne(r.depthTexture,0);const te=O.__webglTexture,ie=tt(r),B=U?e.TEXTURE_CUBE_MAP_POSITIVE_X+A:e.TEXTURE_2D,X=r.depthTexture.format===qt?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;if(r.depthTexture.format===Jt)at(r)?g.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,X,B,te,0,ie):e.framebufferTexture2D(e.FRAMEBUFFER,X,B,te,0);else if(r.depthTexture.format===qt)at(r)?g.framebufferTexture2DMultisampleEXT(e.FRAMEBUFFER,X,B,te,0,ie):e.framebufferTexture2D(e.FRAMEBUFFER,X,B,te,0);else throw new Error("THREE.WebGLTextures: Unknown depthTexture format.")}function we(u){const r=i.get(u),A=u.isWebGLCubeRenderTarget===!0;if(r.__boundDepthTexture!==u.depthTexture){const U=u.depthTexture;if(r.__depthDisposeCallback&&r.__depthDisposeCallback(),U){const O=()=>{delete r.__boundDepthTexture,delete r.__depthDisposeCallback,U.removeEventListener("dispose",O)};U.addEventListener("dispose",O),r.__depthDisposeCallback=O}r.__boundDepthTexture=U}if(u.depthTexture&&!r.__autoAllocateDepthBuffer)if(A)for(let U=0;U<6;U++)st(r.__webglFramebuffer[U],u,U);else{const U=u.texture.mipmaps;U&&U.length>0?st(r.__webglFramebuffer[0],u,0):st(r.__webglFramebuffer,u,0)}else if(A){r.__webglDepthbuffer=[];for(let U=0;U<6;U++)if(t.bindFramebuffer(e.FRAMEBUFFER,r.__webglFramebuffer[U]),r.__webglDepthbuffer[U]===void 0)r.__webglDepthbuffer[U]=e.createRenderbuffer(),ye(r.__webglDepthbuffer[U],u,!1);else{const O=u.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,te=r.__webglDepthbuffer[U];e.bindRenderbuffer(e.RENDERBUFFER,te),e.framebufferRenderbuffer(e.FRAMEBUFFER,O,e.RENDERBUFFER,te)}}else{const U=u.texture.mipmaps;if(U&&U.length>0?t.bindFramebuffer(e.FRAMEBUFFER,r.__webglFramebuffer[0]):t.bindFramebuffer(e.FRAMEBUFFER,r.__webglFramebuffer),r.__webglDepthbuffer===void 0)r.__webglDepthbuffer=e.createRenderbuffer(),ye(r.__webglDepthbuffer,u,!1);else{const O=u.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,te=r.__webglDepthbuffer;e.bindRenderbuffer(e.RENDERBUFFER,te),e.framebufferRenderbuffer(e.FRAMEBUFFER,O,e.RENDERBUFFER,te)}}t.bindFramebuffer(e.FRAMEBUFFER,null)}function Be(u,r,A){const U=i.get(u);r!==void 0&&me(U.__webglFramebuffer,u,u.texture,e.COLOR_ATTACHMENT0,e.TEXTURE_2D,0),A!==void 0&&we(u)}function Ke(u){const r=u.texture,A=i.get(u),U=i.get(r);u.addEventListener("dispose",c);const O=u.textures,te=u.isWebGLCubeRenderTarget===!0,ie=O.length>1;if(ie||(U.__webglTexture===void 0&&(U.__webglTexture=e.createTexture()),U.__version=r.version,d.memory.textures++),te){A.__webglFramebuffer=[];for(let B=0;B<6;B++)if(r.mipmaps&&r.mipmaps.length>0){A.__webglFramebuffer[B]=[];for(let X=0;X<r.mipmaps.length;X++)A.__webglFramebuffer[B][X]=e.createFramebuffer()}else A.__webglFramebuffer[B]=e.createFramebuffer()}else{if(r.mipmaps&&r.mipmaps.length>0){A.__webglFramebuffer=[];for(let B=0;B<r.mipmaps.length;B++)A.__webglFramebuffer[B]=e.createFramebuffer()}else A.__webglFramebuffer=e.createFramebuffer();if(ie)for(let B=0,X=O.length;B<X;B++){const re=i.get(O[B]);re.__webglTexture===void 0&&(re.__webglTexture=e.createTexture(),d.memory.textures++)}if(u.samples>0&&at(u)===!1){A.__webglMultisampledFramebuffer=e.createFramebuffer(),A.__webglColorRenderbuffer=[],t.bindFramebuffer(e.FRAMEBUFFER,A.__webglMultisampledFramebuffer);for(let B=0;B<O.length;B++){const X=O[B];A.__webglColorRenderbuffer[B]=e.createRenderbuffer(),e.bindRenderbuffer(e.RENDERBUFFER,A.__webglColorRenderbuffer[B]);const re=o.convert(X.format,X.colorSpace),xe=o.convert(X.type),le=h(X.internalFormat,re,xe,X.normalized,X.colorSpace,u.isXRRenderTarget===!0),ae=tt(u);e.renderbufferStorageMultisample(e.RENDERBUFFER,ae,le,u.width,u.height),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+B,e.RENDERBUFFER,A.__webglColorRenderbuffer[B])}e.bindRenderbuffer(e.RENDERBUFFER,null),u.depthBuffer&&(A.__webglDepthRenderbuffer=e.createRenderbuffer(),ye(A.__webglDepthRenderbuffer,u,!0)),t.bindFramebuffer(e.FRAMEBUFFER,null)}}if(te){t.bindTexture(e.TEXTURE_CUBE_MAP,U.__webglTexture),ke(e.TEXTURE_CUBE_MAP,r);for(let B=0;B<6;B++)if(r.mipmaps&&r.mipmaps.length>0)for(let X=0;X<r.mipmaps.length;X++)me(A.__webglFramebuffer[B][X],u,r,e.COLOR_ATTACHMENT0,e.TEXTURE_CUBE_MAP_POSITIVE_X+B,X);else me(A.__webglFramebuffer[B],u,r,e.COLOR_ATTACHMENT0,e.TEXTURE_CUBE_MAP_POSITIVE_X+B,0);s(r)&&L(e.TEXTURE_CUBE_MAP),t.unbindTexture()}else if(ie){for(let B=0,X=O.length;B<X;B++){const re=O[B],xe=i.get(re);let le=e.TEXTURE_2D;(u.isWebGL3DRenderTarget||u.isWebGLArrayRenderTarget)&&(le=u.isWebGL3DRenderTarget?e.TEXTURE_3D:e.TEXTURE_2D_ARRAY),t.bindTexture(le,xe.__webglTexture),ke(le,re),me(A.__webglFramebuffer,u,re,e.COLOR_ATTACHMENT0+B,le,0),s(re)&&L(le)}t.unbindTexture()}else{let B=e.TEXTURE_2D;if((u.isWebGL3DRenderTarget||u.isWebGLArrayRenderTarget)&&(B=u.isWebGL3DRenderTarget?e.TEXTURE_3D:e.TEXTURE_2D_ARRAY),t.bindTexture(B,U.__webglTexture),ke(B,r),r.mipmaps&&r.mipmaps.length>0)for(let X=0;X<r.mipmaps.length;X++)me(A.__webglFramebuffer[X],u,r,e.COLOR_ATTACHMENT0,B,X);else me(A.__webglFramebuffer,u,r,e.COLOR_ATTACHMENT0,B,0);s(r)&&L(B),t.unbindTexture()}u.depthBuffer&&we(u)}function Ie(u){const r=u.textures;for(let A=0,U=r.length;A<U;A++){const O=r[A];if(s(O)){const te=z(u),ie=i.get(O).__webglTexture;t.bindTexture(te,ie),L(te),t.unbindTexture()}}}const je=[],ft=[];function ht(u){if(u.samples>0){if(at(u)===!1){const r=u.textures,A=u.width,U=u.height;let O=e.COLOR_BUFFER_BIT;const te=u.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT,ie=i.get(u),B=r.length>1;if(B)for(let re=0;re<r.length;re++)t.bindFramebuffer(e.FRAMEBUFFER,ie.__webglMultisampledFramebuffer),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+re,e.RENDERBUFFER,null),t.bindFramebuffer(e.FRAMEBUFFER,ie.__webglFramebuffer),e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0+re,e.TEXTURE_2D,null,0);t.bindFramebuffer(e.READ_FRAMEBUFFER,ie.__webglMultisampledFramebuffer);const X=u.texture.mipmaps;X&&X.length>0?t.bindFramebuffer(e.DRAW_FRAMEBUFFER,ie.__webglFramebuffer[0]):t.bindFramebuffer(e.DRAW_FRAMEBUFFER,ie.__webglFramebuffer);for(let re=0;re<r.length;re++){if(u.resolveDepthBuffer&&(u.depthBuffer&&(O|=e.DEPTH_BUFFER_BIT),u.stencilBuffer&&u.resolveStencilBuffer&&(O|=e.STENCIL_BUFFER_BIT)),B){e.framebufferRenderbuffer(e.READ_FRAMEBUFFER,e.COLOR_ATTACHMENT0,e.RENDERBUFFER,ie.__webglColorRenderbuffer[re]);const xe=i.get(r[re]).__webglTexture;e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0,e.TEXTURE_2D,xe,0)}e.blitFramebuffer(0,0,A,U,0,0,A,U,O,e.NEAREST),R===!0&&(je.length=0,ft.length=0,je.push(e.COLOR_ATTACHMENT0+re),u.depthBuffer&&u.storeMultisampledDepthBuffer===!1&&(je.push(te),ft.push(te),e.invalidateFramebuffer(e.DRAW_FRAMEBUFFER,ft)),e.invalidateFramebuffer(e.READ_FRAMEBUFFER,je))}if(t.bindFramebuffer(e.READ_FRAMEBUFFER,null),t.bindFramebuffer(e.DRAW_FRAMEBUFFER,null),B)for(let re=0;re<r.length;re++){t.bindFramebuffer(e.FRAMEBUFFER,ie.__webglMultisampledFramebuffer),e.framebufferRenderbuffer(e.FRAMEBUFFER,e.COLOR_ATTACHMENT0+re,e.RENDERBUFFER,ie.__webglColorRenderbuffer[re]);const xe=i.get(r[re]).__webglTexture;t.bindFramebuffer(e.FRAMEBUFFER,ie.__webglFramebuffer),e.framebufferTexture2D(e.DRAW_FRAMEBUFFER,e.COLOR_ATTACHMENT0+re,e.TEXTURE_2D,xe,0)}t.bindFramebuffer(e.DRAW_FRAMEBUFFER,ie.__webglMultisampledFramebuffer)}else if(u.depthBuffer&&u.storeMultisampledDepthBuffer===!1&&R){const r=u.stencilBuffer?e.DEPTH_STENCIL_ATTACHMENT:e.DEPTH_ATTACHMENT;e.invalidateFramebuffer(e.DRAW_FRAMEBUFFER,[r])}}}function tt(u){return Math.min(l.maxSamples,u.samples)}function at(u){const r=i.get(u);return u.samples>0&&n.has("WEBGL_multisampled_render_to_texture")===!0&&r.__useRenderToTexture!==!1}function x(u){const r=d.render.frame;H.get(u)!==r&&(H.set(u,r),u.update())}function dt(u,r){const A=u.colorSpace,U=u.format,O=u.type;return u.isCompressedTexture===!0||u.isVideoTexture===!0||A!==Or&&A!==Yt&&(nt.getTransfer(A)===$e?(U!==Ut||O!==Ct)&&We("WebGLTextures: sRGB encoded textures have to use RGBAFormat and UnsignedByteType."):Je("WebGLTextures: Unsupported texture color space:",A)),r}function Ve(u){return typeof HTMLImageElement<"u"&&u instanceof HTMLImageElement?(T.width=u.naturalWidth||u.width,T.height=u.naturalHeight||u.height):typeof VideoFrame<"u"&&u instanceof VideoFrame?(T.width=u.displayWidth,T.height=u.displayHeight):(T.width=u.width,T.height=u.height),T}this.allocateTextureUnit=Q,this.resetTextureUnits=q,this.getTextureUnits=P,this.setTextureUnits=Y,this.setTexture2D=ne,this.setTexture2DArray=Z,this.setTexture3D=j,this.setTextureCube=ee,this.rebindTextures=Be,this.setupRenderTarget=Ke,this.updateRenderTargetMipmap=Ie,this.updateMultisampleRenderTarget=ht,this.setupDepthRenderbuffer=we,this.setupFrameBufferTexture=me,this.useMultisampledRTT=at,this.isReversedDepthBuffer=function(){return t.buffers.depth.getReversed()}}function sd(e,n){function t(i,l=Yt){let o;const d=nt.getTransfer(l);if(i===Ct)return e.UNSIGNED_BYTE;if(i===xr)return e.UNSIGNED_SHORT_4_4_4_4;if(i===Mr)return e.UNSIGNED_SHORT_5_5_5_1;if(i===ja)return e.UNSIGNED_INT_5_9_9_9_REV;if(i===eo)return e.UNSIGNED_INT_10F_11F_11F_REV;if(i===to)return e.BYTE;if(i===no)return e.SHORT;if(i===En)return e.UNSIGNED_SHORT;if(i===Cr)return e.INT;if(i===Wt)return e.UNSIGNED_INT;if(i===Bt)return e.FLOAT;if(i===Dt)return e.HALF_FLOAT;if(i===io)return e.ALPHA;if(i===ro)return e.RGB;if(i===Ut)return e.RGBA;if(i===Jt)return e.DEPTH_COMPONENT;if(i===qt)return e.DEPTH_STENCIL;if(i===ao)return e.RED;if(i===Er)return e.RED_INTEGER;if(i===Qt)return e.RG;if(i===Sr)return e.RG_INTEGER;if(i===vr)return e.RGBA_INTEGER;if(i===Ln||i===Un||i===wn||i===Dn)if(d===$e)if(o=n.get("WEBGL_compressed_texture_s3tc_srgb"),o!==null){if(i===Ln)return o.COMPRESSED_SRGB_S3TC_DXT1_EXT;if(i===Un)return o.COMPRESSED_SRGB_ALPHA_S3TC_DXT1_EXT;if(i===wn)return o.COMPRESSED_SRGB_ALPHA_S3TC_DXT3_EXT;if(i===Dn)return o.COMPRESSED_SRGB_ALPHA_S3TC_DXT5_EXT}else return null;else if(o=n.get("WEBGL_compressed_texture_s3tc"),o!==null){if(i===Ln)return o.COMPRESSED_RGB_S3TC_DXT1_EXT;if(i===Un)return o.COMPRESSED_RGBA_S3TC_DXT1_EXT;if(i===wn)return o.COMPRESSED_RGBA_S3TC_DXT3_EXT;if(i===Dn)return o.COMPRESSED_RGBA_S3TC_DXT5_EXT}else return null;if(i===_i||i===gi||i===vi||i===Si)if(o=n.get("WEBGL_compressed_texture_pvrtc"),o!==null){if(i===_i)return o.COMPRESSED_RGB_PVRTC_4BPPV1_IMG;if(i===gi)return o.COMPRESSED_RGB_PVRTC_2BPPV1_IMG;if(i===vi)return o.COMPRESSED_RGBA_PVRTC_4BPPV1_IMG;if(i===Si)return o.COMPRESSED_RGBA_PVRTC_2BPPV1_IMG}else return null;if(i===Ei||i===xi||i===Mi||i===Ti||i===Ai||i===zn||i===Ri)if(o=n.get("WEBGL_compressed_texture_etc"),o!==null){if(i===Ei||i===xi)return d===$e?o.COMPRESSED_SRGB8_ETC2:o.COMPRESSED_RGB8_ETC2;if(i===Mi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ETC2_EAC:o.COMPRESSED_RGBA8_ETC2_EAC;if(i===Ti)return o.COMPRESSED_R11_EAC;if(i===Ai)return o.COMPRESSED_SIGNED_R11_EAC;if(i===zn)return o.COMPRESSED_RG11_EAC;if(i===Ri)return o.COMPRESSED_SIGNED_RG11_EAC}else return null;if(i===bi||i===Ci||i===Pi||i===Li||i===Ui||i===wi||i===Di||i===Ii||i===Ni||i===yi||i===Fi||i===Oi||i===Bi||i===Gi)if(o=n.get("WEBGL_compressed_texture_astc"),o!==null){if(i===bi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_4x4_KHR:o.COMPRESSED_RGBA_ASTC_4x4_KHR;if(i===Ci)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_5x4_KHR:o.COMPRESSED_RGBA_ASTC_5x4_KHR;if(i===Pi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_5x5_KHR:o.COMPRESSED_RGBA_ASTC_5x5_KHR;if(i===Li)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_6x5_KHR:o.COMPRESSED_RGBA_ASTC_6x5_KHR;if(i===Ui)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_6x6_KHR:o.COMPRESSED_RGBA_ASTC_6x6_KHR;if(i===wi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_8x5_KHR:o.COMPRESSED_RGBA_ASTC_8x5_KHR;if(i===Di)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_8x6_KHR:o.COMPRESSED_RGBA_ASTC_8x6_KHR;if(i===Ii)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_8x8_KHR:o.COMPRESSED_RGBA_ASTC_8x8_KHR;if(i===Ni)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_10x5_KHR:o.COMPRESSED_RGBA_ASTC_10x5_KHR;if(i===yi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_10x6_KHR:o.COMPRESSED_RGBA_ASTC_10x6_KHR;if(i===Fi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_10x8_KHR:o.COMPRESSED_RGBA_ASTC_10x8_KHR;if(i===Oi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_10x10_KHR:o.COMPRESSED_RGBA_ASTC_10x10_KHR;if(i===Bi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_12x10_KHR:o.COMPRESSED_RGBA_ASTC_12x10_KHR;if(i===Gi)return d===$e?o.COMPRESSED_SRGB8_ALPHA8_ASTC_12x12_KHR:o.COMPRESSED_RGBA_ASTC_12x12_KHR}else return null;if(i===Hi||i===Vi||i===Wi)if(o=n.get("EXT_texture_compression_bptc"),o!==null){if(i===Hi)return d===$e?o.COMPRESSED_SRGB_ALPHA_BPTC_UNORM_EXT:o.COMPRESSED_RGBA_BPTC_UNORM_EXT;if(i===Vi)return o.COMPRESSED_RGB_BPTC_SIGNED_FLOAT_EXT;if(i===Wi)return o.COMPRESSED_RGB_BPTC_UNSIGNED_FLOAT_EXT}else return null;if(i===ki||i===zi||i===Xn||i===Xi)if(o=n.get("EXT_texture_compression_rgtc"),o!==null){if(i===ki)return o.COMPRESSED_RED_RGTC1_EXT;if(i===zi)return o.COMPRESSED_SIGNED_RED_RGTC1_EXT;if(i===Xn)return o.COMPRESSED_RED_GREEN_RGTC2_EXT;if(i===Xi)return o.COMPRESSED_SIGNED_RED_GREEN_RGTC2_EXT}else return null;return i===ln?e.UNSIGNED_INT_24_8:e[i]!==void 0?e[i]:null}return{convert:t}}const ld=`
void main() {

	gl_Position = vec4( position, 1.0 );

}`,cd=`
uniform sampler2DArray depthColor;
uniform float depthWidth;
uniform float depthHeight;

void main() {

	vec2 coord = vec2( gl_FragCoord.x / depthWidth, gl_FragCoord.y / depthHeight );

	if ( coord.x >= 1.0 ) {

		gl_FragDepth = texture( depthColor, vec3( coord.x - 1.0, coord.y, 1 ) ).r;

	} else {

		gl_FragDepth = texture( depthColor, vec3( coord.x, coord.y, 0 ) ).r;

	}

}`;class fd{constructor(){this.texture=null,this.mesh=null,this.depthNear=0,this.depthFar=0}init(n,t){if(this.texture===null){const i=new br(n.texture);(n.depthNear!==t.depthNear||n.depthFar!==t.depthFar)&&(this.depthNear=n.depthNear,this.depthFar=n.depthFar),this.texture=i}}getMesh(n){if(this.texture!==null&&this.mesh===null){const t=n.cameras[0].viewport,i=new It({vertexShader:ld,fragmentShader:cd,uniforms:{depthColor:{value:this.texture},depthWidth:{value:t.z},depthHeight:{value:t.w}}});this.mesh=new Nt(new Tr(20,20),i)}return this.mesh}reset(){this.texture=null,this.mesh=null}getDepthTexture(){return this.texture}}class dd extends Na{constructor(n,t){super();const i=this;let l=null,o=1,d=null,g="local-floor",R=1,T=null,H=null,I=null,p=null,M=null,N=null;const W=typeof XRWebGLBinding<"u",f=new fd,s={},L=t.getContextAttributes();let z=null,h=null;const S=[],m=[],w=new gt;let c=null,_=null;const D=new _n;D.viewport=new _t;const F=new _n;F.viewport=new _t;const G=[D,F],q=new ya;let P=null,Y=null;this.cameraAutoUpdate=!0,this.enabled=!1,this.isPresenting=!1,this.getController=function(V){let $=S[V];return $===void 0&&($=new Pn,S[V]=$),$.getTargetRaySpace()},this.getControllerGrip=function(V){let $=S[V];return $===void 0&&($=new Pn,S[V]=$),$.getGripSpace()},this.getHand=function(V){let $=S[V];return $===void 0&&($=new Pn,S[V]=$),$.getHandSpace()};function Q(V){const $=m.indexOf(V.inputSource);if($===-1)return;const Ee=S[$];Ee!==void 0&&(Ee.update(V.inputSource,V.frame,T||d),Ee.dispatchEvent({type:V.type,data:V.inputSource}))}function K(){l.removeEventListener("select",Q),l.removeEventListener("selectstart",Q),l.removeEventListener("selectend",Q),l.removeEventListener("squeeze",Q),l.removeEventListener("squeezestart",Q),l.removeEventListener("squeezeend",Q),l.removeEventListener("end",K),l.removeEventListener("inputsourceschange",ne);for(let V=0;V<S.length;V++){const $=m[V];$!==null&&(m[V]=null,S[V].disconnect($))}P=null,Y=null,f.reset();for(const V in s)delete s[V];if(n.setRenderTarget(z),M=null,p=null,I=null,l=null,h=null,ze.stop(),i.isPresenting=!1,n.setPixelRatio(c),n.setSize(w.width,w.height,!1),_!==null){const V=_.camera;V.fov=_.fov,V.zoom=_.zoom,V.updateProjectionMatrix(),_=null}i.dispatchEvent({type:"sessionend"})}this.setFramebufferScaleFactor=function(V){o=V,i.isPresenting===!0&&We("WebXRManager: Cannot change framebuffer scale while presenting.")},this.setReferenceSpaceType=function(V){g=V,i.isPresenting===!0&&We("WebXRManager: Cannot change reference space type while presenting.")},this.getReferenceSpace=function(){return T||d},this.setReferenceSpace=function(V){T=V},this.getBaseLayer=function(){return p!==null?p:M},this.getBinding=function(){return I===null&&W&&(I=new XRWebGLBinding(l,t)),I},this.getFrame=function(){return N},this.getSession=function(){return l},this.setSession=async function(V){if(l=V,l!==null){if(z=n.getRenderTarget(),l.addEventListener("select",Q),l.addEventListener("selectstart",Q),l.addEventListener("selectend",Q),l.addEventListener("squeeze",Q),l.addEventListener("squeezestart",Q),l.addEventListener("squeezeend",Q),l.addEventListener("end",K),l.addEventListener("inputsourceschange",ne),L.xrCompatible!==!0&&await t.makeXRCompatible(),c=n.getPixelRatio(),n.getSize(w),W&&"createProjectionLayer"in XRWebGLBinding.prototype){let Ee=null,Ue=null,me=null;L.depth&&(me=L.stencil?t.DEPTH24_STENCIL8:t.DEPTH_COMPONENT24,Ee=L.stencil?qt:Jt,Ue=L.stencil?ln:Wt);const ye={colorFormat:t.RGBA8,depthFormat:me,scaleFactor:o};I=this.getBinding(),p=I.createProjectionLayer(ye),l.updateRenderState({layers:[p]}),n.setPixelRatio(1),n.setSize(p.textureWidth,p.textureHeight,!1),h=new Mt(p.textureWidth,p.textureHeight,{format:Ut,type:Ct,depthTexture:new Sn(p.textureWidth,p.textureHeight,Ue,void 0,void 0,void 0,void 0,void 0,void 0,Ee),stencilBuffer:L.stencil,colorSpace:n.outputColorSpace,samples:L.antialias?4:0,resolveDepthBuffer:p.ignoreDepthValues===!1,resolveStencilBuffer:p.ignoreDepthValues===!1,storeMultisampledDepthBuffer:p.ignoreDepthValues===!1,storeMultisampledStencilBuffer:p.ignoreDepthValues===!1})}else{const Ee={antialias:L.antialias,alpha:!0,depth:L.depth,stencil:L.stencil,framebufferScaleFactor:o};M=new XRWebGLLayer(l,t,Ee),l.updateRenderState({baseLayer:M}),n.setPixelRatio(1),n.setSize(M.framebufferWidth,M.framebufferHeight,!1),h=new Mt(M.framebufferWidth,M.framebufferHeight,{format:Ut,type:Ct,colorSpace:n.outputColorSpace,stencilBuffer:L.stencil,resolveDepthBuffer:M.ignoreDepthValues===!1,resolveStencilBuffer:M.ignoreDepthValues===!1,storeMultisampledDepthBuffer:M.ignoreDepthValues===!1,storeMultisampledStencilBuffer:M.ignoreDepthValues===!1})}h.isXRRenderTarget=!0,this.setFoveation(R),T=null,d=await l.requestReferenceSpace(g),ze.setContext(l),ze.start(),i.isPresenting=!0,i.dispatchEvent({type:"sessionstart"})}},this.getEnvironmentBlendMode=function(){if(l!==null)return l.environmentBlendMode},this.getDepthTexture=function(){return f.getDepthTexture()};function ne(V){for(let $=0;$<V.removed.length;$++){const Ee=V.removed[$],Ue=m.indexOf(Ee);Ue>=0&&(m[Ue]=null,S[Ue].disconnect(Ee))}for(let $=0;$<V.added.length;$++){const Ee=V.added[$];let Ue=m.indexOf(Ee);if(Ue===-1){for(let ye=0;ye<S.length;ye++)if(ye>=m.length){m.push(Ee),Ue=ye;break}else if(m[ye]===null){m[ye]=Ee,Ue=ye;break}if(Ue===-1)break}const me=S[Ue];me&&me.connect(Ee)}}const Z=new Ne,j=new Ne;function ee(V,$,Ee){Z.setFromMatrixPosition($.matrixWorld),j.setFromMatrixPosition(Ee.matrixWorld);const Ue=Z.distanceTo(j),me=$.projectionMatrix.elements,ye=Ee.projectionMatrix.elements,st=me[14]/(me[10]-1),we=me[14]/(me[10]+1),Be=(me[9]+1)/me[5],Ke=(me[9]-1)/me[5],Ie=(me[8]-1)/me[0],je=(ye[8]+1)/ye[0],ft=st*Ie,ht=st*je,tt=Ue/(-Ie+je),at=tt*-Ie;if($.matrixWorld.decompose(V.position,V.quaternion,V.scale),V.translateX(at),V.translateZ(tt),V.matrixWorld.compose(V.position,V.quaternion,V.scale),V.matrixWorldInverse.copy(V.matrixWorld).invert(),me[10]===-1)V.projectionMatrix.copy($.projectionMatrix),V.projectionMatrixInverse.copy($.projectionMatrixInverse);else{const x=st+tt,dt=we+tt,Ve=ft-at,u=ht+(Ue-at),r=Be*we/dt*x,A=Ke*we/dt*x;V.projectionMatrix.makePerspective(Ve,u,r,A,x,dt),V.projectionMatrixInverse.copy(V.projectionMatrix).invert()}}function be(V,$){$===null?V.matrixWorld.copy(V.matrix):V.matrixWorld.multiplyMatrices($.matrixWorld,V.matrix),V.matrixWorldInverse.copy(V.matrixWorld).invert()}this.updateCamera=function(V){if(l===null)return;let $=V.near,Ee=V.far;f.texture!==null&&(f.depthNear>0&&($=f.depthNear),f.depthFar>0&&(Ee=f.depthFar)),q.near=F.near=D.near=$,q.far=F.far=D.far=Ee,(P!==q.near||Y!==q.far)&&(l.updateRenderState({depthNear:q.near,depthFar:q.far}),P=q.near,Y=q.far),q.layers.mask=V.layers.mask|6,D.layers.mask=q.layers.mask&-5,F.layers.mask=q.layers.mask&-3;const Ue=V.parent,me=q.cameras;be(q,Ue);for(let ye=0;ye<me.length;ye++)be(me[ye],Ue);me.length===2?ee(q,D,F):q.projectionMatrix.copy(D.projectionMatrix),_===null&&V.isPerspectiveCamera&&(_={camera:V,fov:V.fov,zoom:V.zoom}),Re(V,q,Ue)};function Re(V,$,Ee){Ee===null?V.matrix.copy($.matrixWorld):(V.matrix.copy(Ee.matrixWorld),V.matrix.invert(),V.matrix.multiply($.matrixWorld)),V.matrix.decompose(V.position,V.quaternion,V.scale),V.updateMatrixWorld(!0),V.projectionMatrix.copy($.projectionMatrix),V.projectionMatrixInverse.copy($.projectionMatrixInverse),V.isPerspectiveCamera&&(V.fov=Fa*2*Math.atan(1/V.projectionMatrix.elements[5]),V.zoom=1)}this.getCamera=function(){return q},this.getFoveation=function(){if(!(p===null&&M===null))return R},this.setFoveation=function(V){R=V,p!==null&&(p.fixedFoveation=V),M!==null&&M.fixedFoveation!==void 0&&(M.fixedFoveation=V)},this.hasDepthSensing=function(){return f.texture!==null},this.getDepthSensingMesh=function(){return f.getMesh(q)},this.getCameraTexture=function(V){return s[V]};let it=null;function ke(V,$){if(H=$.getViewerPose(T||d),N=$,H!==null){const Ee=H.views;M!==null&&(n.setRenderTargetFramebuffer(h,M.framebuffer),n.setRenderTarget(h));let Ue=!1;Ee.length!==q.cameras.length&&(q.cameras.length=0,Ue=!0);for(let we=0;we<Ee.length;we++){const Be=Ee[we];let Ke=null;if(M!==null)Ke=M.getViewport(Be);else{const je=I.getViewSubImage(p,Be);Ke=je.viewport,we===0&&(n.setRenderTargetTextures(h,je.colorTexture,je.depthStencilTexture),n.setRenderTarget(h))}let Ie=G[we];Ie===void 0&&(Ie=new _n,Ie.layers.enable(we),Ie.viewport=new _t,G[we]=Ie),Ie.matrix.fromArray(Be.transform.matrix),Ie.matrix.decompose(Ie.position,Ie.quaternion,Ie.scale),Ie.projectionMatrix.fromArray(Be.projectionMatrix),Ie.projectionMatrixInverse.copy(Ie.projectionMatrix).invert(),Ie.viewport.set(Ke.x,Ke.y,Ke.width,Ke.height),we===0&&(q.matrix.copy(Ie.matrix),q.matrix.decompose(q.position,q.quaternion,q.scale)),Ue===!0&&q.cameras.push(Ie)}const me=l.enabledFeatures;if(me&&me.includes("depth-sensing")&&l.depthUsage=="gpu-optimized"&&W){I=i.getBinding();const we=I.getDepthInformation(Ee[0]);we&&we.isValid&&we.texture&&f.init(we,l.renderState)}if(me&&me.includes("camera-access")&&W){n.state.unbindTexture(),I=i.getBinding();for(let we=0;we<Ee.length;we++){const Be=Ee[we].camera;if(Be){let Ke=s[Be];Ke||(Ke=new br,s[Be]=Ke);const Ie=I.getCameraImage(Be);Ke.sourceTexture=Ie}}}}for(let Ee=0;Ee<S.length;Ee++){const Ue=m[Ee],me=S[Ee];Ue!==null&&me!==void 0&&me.update(Ue,$,T||d)}it&&it(V,$),$.detectedPlanes&&i.dispatchEvent({type:"planesdetected",data:$}),N=null}const ze=new Br;ze.setAnimationLoop(ke),this.setAnimationLoop=function(V){it=V},this.dispose=function(){}}}const ud=new $t,Xr=new Fe;Xr.set(-1,0,0,0,1,0,0,0,1);function pd(e,n){function t(f,s){f.matrixAutoUpdate===!0&&f.updateMatrix(),s.value.copy(f.matrix)}function i(f,s){s.color.getRGB(f.fogColor.value,Ar(e)),s.isFog?(f.fogNear.value=s.near,f.fogFar.value=s.far):s.isFogExp2&&(f.fogDensity.value=s.density)}function l(f,s,L,z,h){s.isNodeMaterial?s.uniformsNeedUpdate=!1:s.isMeshBasicMaterial?o(f,s):s.isMeshLambertMaterial?(o(f,s),s.envMap&&(f.envMapIntensity.value=s.envMapIntensity)):s.isMeshToonMaterial?(o(f,s),I(f,s)):s.isMeshPhongMaterial?(o(f,s),H(f,s),s.envMap&&(f.envMapIntensity.value=s.envMapIntensity)):s.isMeshStandardMaterial?(o(f,s),p(f,s),s.isMeshPhysicalMaterial&&M(f,s,h)):s.isMeshMatcapMaterial?(o(f,s),N(f,s)):s.isMeshDepthMaterial?o(f,s):s.isMeshDistanceMaterial?(o(f,s),W(f,s)):s.isMeshNormalMaterial?o(f,s):s.isLineBasicMaterial?(d(f,s),s.isLineDashedMaterial&&g(f,s)):s.isPointsMaterial?R(f,s,L,z):s.isSpriteMaterial?T(f,s):s.isShadowMaterial?(f.color.value.copy(s.color),f.opacity.value=s.opacity):s.isShaderMaterial&&(s.uniformsNeedUpdate=!1)}function o(f,s){f.opacity.value=s.opacity,s.color&&f.diffuse.value.copy(s.color),s.emissive&&f.emissive.value.copy(s.emissive).multiplyScalar(s.emissiveIntensity),s.map&&(f.map.value=s.map,t(s.map,f.mapTransform)),s.alphaMap&&(f.alphaMap.value=s.alphaMap,t(s.alphaMap,f.alphaMapTransform)),s.bumpMap&&(f.bumpMap.value=s.bumpMap,t(s.bumpMap,f.bumpMapTransform),f.bumpScale.value=s.bumpScale,s.side===St&&(f.bumpScale.value*=-1)),s.normalMap&&(f.normalMap.value=s.normalMap,t(s.normalMap,f.normalMapTransform),f.normalScale.value.copy(s.normalScale),s.side===St&&f.normalScale.value.negate()),s.displacementMap&&(f.displacementMap.value=s.displacementMap,t(s.displacementMap,f.displacementMapTransform),f.displacementScale.value=s.displacementScale,f.displacementBias.value=s.displacementBias),s.emissiveMap&&(f.emissiveMap.value=s.emissiveMap,t(s.emissiveMap,f.emissiveMapTransform)),s.specularMap&&(f.specularMap.value=s.specularMap,t(s.specularMap,f.specularMapTransform)),s.alphaTest>0&&(f.alphaTest.value=s.alphaTest);const L=n.get(s),z=L.envMap,h=L.envMapRotation;z&&(f.envMap.value=z,f.envMapRotation.value.setFromMatrix4(ud.makeRotationFromEuler(h)).transpose(),z.isCubeTexture&&z.isRenderTargetTexture===!1&&f.envMapRotation.value.premultiply(Xr),f.reflectivity.value=s.reflectivity,f.ior.value=s.ior,f.refractionRatio.value=s.refractionRatio),s.lightMap&&(f.lightMap.value=s.lightMap,f.lightMapIntensity.value=s.lightMapIntensity,t(s.lightMap,f.lightMapTransform)),s.aoMap&&(f.aoMap.value=s.aoMap,f.aoMapIntensity.value=s.aoMapIntensity,t(s.aoMap,f.aoMapTransform))}function d(f,s){f.diffuse.value.copy(s.color),f.opacity.value=s.opacity,s.map&&(f.map.value=s.map,t(s.map,f.mapTransform))}function g(f,s){f.dashSize.value=s.dashSize,f.totalSize.value=s.dashSize+s.gapSize,f.scale.value=s.scale}function R(f,s,L,z){f.diffuse.value.copy(s.color),f.opacity.value=s.opacity,f.size.value=s.size*L,f.scale.value=z*.5,s.map&&(f.map.value=s.map,t(s.map,f.uvTransform)),s.alphaMap&&(f.alphaMap.value=s.alphaMap,t(s.alphaMap,f.alphaMapTransform)),s.alphaTest>0&&(f.alphaTest.value=s.alphaTest)}function T(f,s){f.diffuse.value.copy(s.color),f.opacity.value=s.opacity,f.rotation.value=s.rotation,s.map&&(f.map.value=s.map,t(s.map,f.mapTransform)),s.alphaMap&&(f.alphaMap.value=s.alphaMap,t(s.alphaMap,f.alphaMapTransform)),s.alphaTest>0&&(f.alphaTest.value=s.alphaTest)}function H(f,s){f.specular.value.copy(s.specular),f.shininess.value=Math.max(s.shininess,1e-4)}function I(f,s){s.gradientMap&&(f.gradientMap.value=s.gradientMap)}function p(f,s){f.metalness.value=s.metalness,s.metalnessMap&&(f.metalnessMap.value=s.metalnessMap,t(s.metalnessMap,f.metalnessMapTransform)),f.roughness.value=s.roughness,s.roughnessMap&&(f.roughnessMap.value=s.roughnessMap,t(s.roughnessMap,f.roughnessMapTransform)),s.envMap&&(f.envMapIntensity.value=s.envMapIntensity)}function M(f,s,L){f.ior.value=s.ior,s.sheen>0&&(f.sheenColor.value.copy(s.sheenColor).multiplyScalar(s.sheen),f.sheenRoughness.value=s.sheenRoughness,s.sheenColorMap&&(f.sheenColorMap.value=s.sheenColorMap,t(s.sheenColorMap,f.sheenColorMapTransform)),s.sheenRoughnessMap&&(f.sheenRoughnessMap.value=s.sheenRoughnessMap,t(s.sheenRoughnessMap,f.sheenRoughnessMapTransform))),s.clearcoat>0&&(f.clearcoat.value=s.clearcoat,f.clearcoatRoughness.value=s.clearcoatRoughness,s.clearcoatMap&&(f.clearcoatMap.value=s.clearcoatMap,t(s.clearcoatMap,f.clearcoatMapTransform)),s.clearcoatRoughnessMap&&(f.clearcoatRoughnessMap.value=s.clearcoatRoughnessMap,t(s.clearcoatRoughnessMap,f.clearcoatRoughnessMapTransform)),s.clearcoatNormalMap&&(f.clearcoatNormalMap.value=s.clearcoatNormalMap,t(s.clearcoatNormalMap,f.clearcoatNormalMapTransform),f.clearcoatNormalScale.value.copy(s.clearcoatNormalScale),s.side===St&&f.clearcoatNormalScale.value.negate())),s.dispersion>0&&(f.dispersion.value=s.dispersion),s.retroreflectivity>0&&(f.retroreflectivity.value=s.retroreflectivity),s.iridescence>0&&(f.iridescence.value=s.iridescence,f.iridescenceIOR.value=s.iridescenceIOR,f.iridescenceThicknessMinimum.value=s.iridescenceThicknessRange[0],f.iridescenceThicknessMaximum.value=s.iridescenceThicknessRange[1],s.iridescenceMap&&(f.iridescenceMap.value=s.iridescenceMap,t(s.iridescenceMap,f.iridescenceMapTransform)),s.iridescenceThicknessMap&&(f.iridescenceThicknessMap.value=s.iridescenceThicknessMap,t(s.iridescenceThicknessMap,f.iridescenceThicknessMapTransform))),s.transmission>0&&(f.transmission.value=s.transmission,f.transmissionSamplerMap.value=L.texture,f.transmissionSamplerSize.value.set(L.width,L.height),s.transmissionMap&&(f.transmissionMap.value=s.transmissionMap,t(s.transmissionMap,f.transmissionMapTransform)),f.thickness.value=s.thickness,s.thicknessMap&&(f.thicknessMap.value=s.thicknessMap,t(s.thicknessMap,f.thicknessMapTransform)),f.attenuationDistance.value=s.attenuationDistance,f.attenuationColor.value.copy(s.attenuationColor)),s.anisotropy>0&&(f.anisotropyVector.value.set(s.anisotropy*Math.cos(s.anisotropyRotation),s.anisotropy*Math.sin(s.anisotropyRotation)),s.anisotropyMap&&(f.anisotropyMap.value=s.anisotropyMap,t(s.anisotropyMap,f.anisotropyMapTransform))),f.specularIntensity.value=s.specularIntensity,f.specularColor.value.copy(s.specularColor),s.specularColorMap&&(f.specularColorMap.value=s.specularColorMap,t(s.specularColorMap,f.specularColorMapTransform)),s.specularIntensityMap&&(f.specularIntensityMap.value=s.specularIntensityMap,t(s.specularIntensityMap,f.specularIntensityMapTransform))}function N(f,s){s.matcap&&(f.matcap.value=s.matcap)}function W(f,s){const L=n.get(s).light;f.referencePosition.value.setFromMatrixPosition(L.matrixWorld),f.nearDistance.value=L.shadow.camera.near,f.farDistance.value=L.shadow.camera.far}return{refreshFogUniforms:i,refreshMaterialUniforms:l}}function hd(e,n,t,i){let l={},o={},d=[];const g=e.getParameter(e.MAX_UNIFORM_BUFFER_BINDINGS);function R(h,S){const m=S.program;i.uniformBlockBinding(h,m)}function T(h,S){let m=l[h.id];m===void 0&&(f(h),m=H(h),l[h.id]=m,h.addEventListener("dispose",L));const w=S.program;i.updateUBOMapping(h,w);const c=n.render.frame;o[h.id]!==c&&(p(h),o[h.id]=c)}function H(h){const S=I();h.__bindingPointIndex=S;const m=e.createBuffer(),w=h.__size,c=h.usage;return e.bindBuffer(e.UNIFORM_BUFFER,m),e.bufferData(e.UNIFORM_BUFFER,w,c),e.bindBuffer(e.UNIFORM_BUFFER,null),e.bindBufferBase(e.UNIFORM_BUFFER,S,m),m}function I(){for(let h=0;h<g;h++)if(d.indexOf(h)===-1)return d.push(h),h;return Je("WebGLRenderer: Maximum number of simultaneously usable uniforms groups reached."),0}function p(h){const S=l[h.id],m=h.uniforms,w=h.__cache;e.bindBuffer(e.UNIFORM_BUFFER,S);for(let c=0,_=m.length;c<_;c++){const D=m[c];if(Array.isArray(D))for(let F=0,G=D.length;F<G;F++)M(D[F],c,F,w);else M(D,c,0,w)}e.bindBuffer(e.UNIFORM_BUFFER,null)}function M(h,S,m,w){if(W(h,S,m,w)===!0){const c=h.__offset,_=h.value;if(Array.isArray(_)){let D=0;for(let F=0;F<_.length;F++){const G=_[F],q=s(G);N(G,h.__data,D),typeof G!="number"&&typeof G!="boolean"&&!G.isMatrix3&&!ArrayBuffer.isView(G)&&(D+=q.storage/Float32Array.BYTES_PER_ELEMENT)}}else N(_,h.__data,0);e.bufferSubData(e.UNIFORM_BUFFER,c,h.__data)}}function N(h,S,m){typeof h=="number"||typeof h=="boolean"?S[0]=h:h.isMatrix3?(S[0]=h.elements[0],S[1]=h.elements[1],S[2]=h.elements[2],S[3]=0,S[4]=h.elements[3],S[5]=h.elements[4],S[6]=h.elements[5],S[7]=0,S[8]=h.elements[6],S[9]=h.elements[7],S[10]=h.elements[8],S[11]=0):ArrayBuffer.isView(h)?S.set(new h.constructor(h.buffer,h.byteOffset,S.length)):h.toArray(S,m)}function W(h,S,m,w){const c=h.value,_=S+"_"+m;if(w[_]===void 0)return typeof c=="number"||typeof c=="boolean"?w[_]=c:ArrayBuffer.isView(c)?w[_]=c.slice():w[_]=c.clone(),!0;{const D=w[_];if(typeof c=="number"||typeof c=="boolean"){if(D!==c)return w[_]=c,!0}else{if(ArrayBuffer.isView(c))return!0;if(D.equals(c)===!1)return D.copy(c),!0}}return!1}function f(h){const S=h.uniforms;let m=0;const w=16;for(let _=0,D=S.length;_<D;_++){const F=Array.isArray(S[_])?S[_]:[S[_]];for(let G=0,q=F.length;G<q;G++){const P=F[G],Y=Array.isArray(P.value)?P.value:[P.value];for(let Q=0,K=Y.length;Q<K;Q++){const ne=Y[Q],Z=s(ne),j=m%w,ee=j%Z.boundary,be=j+ee;m+=ee,be!==0&&w-be<Z.storage&&(m+=w-be),P.__data=new Float32Array(Z.storage/Float32Array.BYTES_PER_ELEMENT),P.__offset=m,m+=Z.storage}}}const c=m%w;return c>0&&(m+=w-c),h.__size=m,h.__cache={},this}function s(h){const S={boundary:0,storage:0};return typeof h=="number"||typeof h=="boolean"?(S.boundary=4,S.storage=4):h.isVector2?(S.boundary=8,S.storage=8):h.isVector3||h.isColor?(S.boundary=16,S.storage=12):h.isVector4?(S.boundary=16,S.storage=16):h.isMatrix3?(S.boundary=48,S.storage=48):h.isMatrix4?(S.boundary=64,S.storage=64):h.isTexture?We("WebGLRenderer: Texture samplers can not be part of an uniforms group."):ArrayBuffer.isView(h)?(S.boundary=16,S.storage=h.byteLength):We("WebGLRenderer: Unsupported uniform value type.",h),S}function L(h){const S=h.target;S.removeEventListener("dispose",L);const m=d.indexOf(S.__bindingPointIndex);d.splice(m,1),e.deleteBuffer(l[S.id]),delete l[S.id],delete o[S.id]}function z(){for(const h in l)e.deleteBuffer(l[h]);d=[],l={},o={}}return{bind:R,update:T,dispose:z}}const md=new Uint16Array([12469,15057,12620,14925,13266,14620,13807,14376,14323,13990,14545,13625,14713,13328,14840,12882,14931,12528,14996,12233,15039,11829,15066,11525,15080,11295,15085,10976,15082,10705,15073,10495,13880,14564,13898,14542,13977,14430,14158,14124,14393,13732,14556,13410,14702,12996,14814,12596,14891,12291,14937,11834,14957,11489,14958,11194,14943,10803,14921,10506,14893,10278,14858,9960,14484,14039,14487,14025,14499,13941,14524,13740,14574,13468,14654,13106,14743,12678,14818,12344,14867,11893,14889,11509,14893,11180,14881,10751,14852,10428,14812,10128,14765,9754,14712,9466,14764,13480,14764,13475,14766,13440,14766,13347,14769,13070,14786,12713,14816,12387,14844,11957,14860,11549,14868,11215,14855,10751,14825,10403,14782,10044,14729,9651,14666,9352,14599,9029,14967,12835,14966,12831,14963,12804,14954,12723,14936,12564,14917,12347,14900,11958,14886,11569,14878,11247,14859,10765,14828,10401,14784,10011,14727,9600,14660,9289,14586,8893,14508,8533,15111,12234,15110,12234,15104,12216,15092,12156,15067,12010,15028,11776,14981,11500,14942,11205,14902,10752,14861,10393,14812,9991,14752,9570,14682,9252,14603,8808,14519,8445,14431,8145,15209,11449,15208,11451,15202,11451,15190,11438,15163,11384,15117,11274,15055,10979,14994,10648,14932,10343,14871,9936,14803,9532,14729,9218,14645,8742,14556,8381,14461,8020,14365,7603,15273,10603,15272,10607,15267,10619,15256,10631,15231,10614,15182,10535,15118,10389,15042,10167,14963,9787,14883,9447,14800,9115,14710,8665,14615,8318,14514,7911,14411,7507,14279,7198,15314,9675,15313,9683,15309,9712,15298,9759,15277,9797,15229,9773,15166,9668,15084,9487,14995,9274,14898,8910,14800,8539,14697,8234,14590,7790,14479,7409,14367,7067,14178,6621,15337,8619,15337,8631,15333,8677,15325,8769,15305,8871,15264,8940,15202,8909,15119,8775,15022,8565,14916,8328,14804,8009,14688,7614,14569,7287,14448,6888,14321,6483,14088,6171,15350,7402,15350,7419,15347,7480,15340,7613,15322,7804,15287,7973,15229,8057,15148,8012,15046,7846,14933,7611,14810,7357,14682,7069,14552,6656,14421,6316,14251,5948,14007,5528,15356,5942,15356,5977,15353,6119,15348,6294,15332,6551,15302,6824,15249,7044,15171,7122,15070,7050,14949,6861,14818,6611,14679,6349,14538,6067,14398,5651,14189,5311,13935,4958,15359,4123,15359,4153,15356,4296,15353,4646,15338,5160,15311,5508,15263,5829,15188,6042,15088,6094,14966,6001,14826,5796,14678,5543,14527,5287,14377,4985,14133,4586,13869,4257,15360,1563,15360,1642,15358,2076,15354,2636,15341,3350,15317,4019,15273,4429,15203,4732,15105,4911,14981,4932,14836,4818,14679,4621,14517,4386,14359,4156,14083,3795,13808,3437,15360,122,15360,137,15358,285,15355,636,15344,1274,15322,2177,15281,2765,15215,3223,15120,3451,14995,3569,14846,3567,14681,3466,14511,3305,14344,3121,14037,2800,13753,2467,15360,0,15360,1,15359,21,15355,89,15346,253,15325,479,15287,796,15225,1148,15133,1492,15008,1749,14856,1882,14685,1886,14506,1783,14324,1608,13996,1398,13702,1183]);let Rt=null;function _d(){return Rt===null&&(Rt=new Oa(md,16,16,Qt,Dt),Rt.name="DFG_LUT",Rt.minFilter=vt,Rt.magFilter=vt,Rt.wrapS=Vn,Rt.wrapT=Vn,Rt.generateMipmaps=!1,Rt.needsUpdate=!0),Rt}class vd{constructor(n={}){const{canvas:t=jr(),context:i=null,depth:l=!0,stencil:o=!1,alpha:d=!1,antialias:g=!1,premultipliedAlpha:R=!0,preserveDrawingBuffer:T=!1,powerPreference:H="default",failIfMajorPerformanceCaveat:I=!1,reversedDepthBuffer:p=!1,outputBufferType:M=Ct}=n;this.isWebGLRenderer=!0;let N;if(i!==null){if(typeof WebGLRenderingContext<"u"&&i instanceof WebGLRenderingContext)throw new Error("THREE.WebGLRenderer: WebGL 1 is not supported since r163.");N=i.getContextAttributes().alpha}else N=d;const W=M,f=new Set([vr,Sr,Er]),s=new Set([Ct,Wt,En,ln,xr,Mr]),L=new Uint32Array(4),z=new Int32Array(4),h=new Ne;let S=null,m=null;const w=[],c=[];let _=null;this.domElement=t,this.debug={checkShaderErrors:!0,diagnostics:{keywords:!1},onShaderError:null},this.autoClear=!0,this.autoClearColor=!0,this.autoClearDepth=!0,this.autoClearStencil=!0,this.sortObjects=!0,this.clippingPlanes=[],this.localClippingEnabled=!1,this.toneMapping=Pt,this.toneMappingExposure=1,this.transmissionResolutionScale=1;const D=this;let F=!1,G=null,q=null,P=null,Y=null;this._outputColorSpace=ea;let Q=0,K=0,ne=null,Z=-1,j=null;const ee=new _t,be=new _t;let Re=null;const it=new et(0);let ke=0,ze=t.width,V=t.height,$=1,Ee=null,Ue=null;const me=new _t(0,0,ze,V),ye=new _t(0,0,ze,V);let st=!1;const we=new _r;let Be=!1,Ke=!1;const Ie=new $t,je=new Ne,ft=new _t,ht={background:null,fog:null,environment:null,overrideMaterial:null,isScene:!0};let tt=!1;function at(){return ne===null?$:1}let x=i;function dt(a,v){return t.getContext(a,v)}let Ve,u,r,A,U,O,te,ie,B,X,re,xe,le,ae,Me,Ae,Ce,E,oe,k,se,ue,J;try{const a={alpha:!0,depth:l,stencil:o,antialias:g,premultipliedAlpha:R,preserveDrawingBuffer:T,powerPreference:H,failIfMajorPerformanceCaveat:I};if("setAttribute"in t&&t.setAttribute("data-engine",`three.js r${ta}`),t.addEventListener("webglcontextlost",qe,!1),t.addEventListener("webglcontextrestored",Ge,!1),t.addEventListener("webglcontextcreationerror",xt,!1),x===null){const v="webgl2";if(x=dt(v,a),x===null)throw dt(v)?new Error("THREE.WebGLRenderer: Error creating WebGL context with your selected attributes."):new Error("THREE.WebGLRenderer: Error creating WebGL context.")}Te()}catch(a){throw t.removeEventListener("webglcontextlost",qe,!1),t.removeEventListener("webglcontextrestored",Ge,!1),t.removeEventListener("webglcontextcreationerror",xt,!1),Je("WebGLRenderer: "+a.message),a}function Te(){Ve=new mc(x),Ve.init(),se=new sd(x,Ve),u=new ac(x,Ve,n,se),r=new ad(x,Ve),u.reversedDepthBuffer&&p&&r.buffers.depth.setReversed(!0),q=x.createFramebuffer(),P=x.createFramebuffer(),Y=x.createFramebuffer(),A=new vc(x),U=new Xf,O=new od(x,Ve,r,U,u,se,A),te=new hc(D),ie=new Eo(x),ue=new ic(x,ie),B=new _c(x,ie,A,ue),X=new Ec(x,B,ie,ue,A),E=new Sc(x,u,O),Me=new oc(U),re=new zf(D,te,Ve,u,ue,Me),xe=new pd(D,U),le=new Kf,ae=new jf(Ve),Ce=new nc(D,te,r,X,N,R),Ae=new rd(D,X,u),J=new hd(x,A,u,r),oe=new rc(x,Ve,A),k=new gc(x,Ve,A),A.programs=re.programs,D.capabilities=u,D.extensions=Ve,D.properties=U,D.renderLists=le,D.shadowMap=Ae,D.state=r,D.info=A}W!==Ct&&(_=new Mc(W,t.width,t.height,g,l,o));const ve=new dd(D,x);this.xr=ve,this.getContext=function(){return x},this.getContextAttributes=function(){return x.getContextAttributes()},this.forceContextLoss=function(){const a=Ve.get("WEBGL_lose_context");a&&a.loseContext()},this.forceContextRestore=function(){const a=Ve.get("WEBGL_lose_context");a&&a.restoreContext()},this.getPixelRatio=function(){return $},this.setPixelRatio=function(a){a!==void 0&&($=a,this.setSize(ze,V,!1))},this.getSize=function(a){return a.set(ze,V)},this.setSize=function(a,v,y=!0){if(ve.isPresenting){We("WebGLRenderer: Can't change size while VR device is presenting.");return}ze=a,V=v,t.width=Math.floor(a*$),t.height=Math.floor(v*$),y===!0&&(t.style.width=a+"px",t.style.height=v+"px"),_!==null&&_.setSize(t.width,t.height),this.setViewport(0,0,a,v)},this.getDrawingBufferSize=function(a){return a.set(ze*$,V*$).floor()},this.setDrawingBufferSize=function(a,v,y){ze=a,V=v,$=y,t.width=Math.floor(a*y),t.height=Math.floor(v*y),this.setViewport(0,0,a,v)},this.setEffects=function(a){if(W===Ct){Je("WebGLRenderer: setEffects() requires outputBufferType set to HalfFloatType or FloatType.");return}if(a){for(let v=0;v<a.length;v++)if(a[v].isOutputPass===!0){We("WebGLRenderer: OutputPass is not needed in setEffects(). Tone mapping and color space conversion are applied automatically.");break}}_.setEffects(a||[])},this.getCurrentViewport=function(a){return a.copy(ee)},this.getViewport=function(a){return a.copy(me)},this.setViewport=function(a,v,y,b){a.isVector4?me.set(a.x,a.y,a.z,a.w):me.set(a,v,y,b),r.viewport(ee.copy(me).multiplyScalar($).round())},this.getScissor=function(a){return a.copy(ye)},this.setScissor=function(a,v,y,b){a.isVector4?ye.set(a.x,a.y,a.z,a.w):ye.set(a,v,y,b),r.scissor(be.copy(ye).multiplyScalar($).round())},this.getScissorTest=function(){return st},this.setScissorTest=function(a){r.setScissorTest(st=a)},this.setOpaqueSort=function(a){Ee=a},this.setTransparentSort=function(a){Ue=a},this.getClearColor=function(a){return a.copy(Ce.getClearColor())},this.setClearColor=function(){Ce.setClearColor(...arguments)},this.getClearAlpha=function(){return Ce.getClearAlpha()},this.setClearAlpha=function(){Ce.setClearAlpha(...arguments)},this.clear=function(a=!0,v=!0,y=!0){let b=0;if(a){let C=!1;if(ne!==null){const de=ne.texture.format;C=f.has(de)}if(C){const de=ne.texture.type,he=s.has(de),fe=Ce.getClearColor(),_e=Ce.getClearAlpha(),Se=fe.r,Pe=fe.g,De=fe.b;he?(L[0]=Se,L[1]=Pe,L[2]=De,L[3]=_e,x.clearBufferuiv(x.COLOR,0,L)):(z[0]=Se,z[1]=Pe,z[2]=De,z[3]=_e,x.clearBufferiv(x.COLOR,0,z))}else b|=x.COLOR_BUFFER_BIT}v&&(b|=x.DEPTH_BUFFER_BIT,this.state.buffers.depth.setMask(!0)),y&&(b|=x.STENCIL_BUFFER_BIT,this.state.buffers.stencil.setMask(4294967295)),b!==0&&x.clear(b)},this.clearColor=function(){this.clear(!0,!1,!1)},this.clearDepth=function(){this.clear(!1,!0,!1)},this.clearStencil=function(){this.clear(!1,!1,!0)},this.setNodesHandler=function(a){a.setRenderer(this),G=a},this.dispose=function(){t.removeEventListener("webglcontextlost",qe,!1),t.removeEventListener("webglcontextrestored",Ge,!1),t.removeEventListener("webglcontextcreationerror",xt,!1),Ce.dispose(),le.dispose(),ae.dispose(),U.dispose(),te.dispose(),X.dispose(),ue.dispose(),J.dispose(),re.dispose(),ve.dispose(),ve.removeEventListener("sessionstart",Jn),ve.removeEventListener("sessionend",jn),Gt.stop()};function qe(a){a.preventDefault(),si("WebGLRenderer: Context Lost."),F=!0}function Ge(){si("WebGLRenderer: Context Restored."),F=!1;const a=A.autoReset,v=Ae.enabled,y=Ae.autoUpdate,b=Ae.needsUpdate,C=Ae.type;Te(),A.autoReset=a,Ae.enabled=v,Ae.autoUpdate=y,Ae.needsUpdate=b,Ae.type=C}function xt(a){Je("WebGLRenderer: A WebGL context could not be created. Reason: ",a.statusMessage)}function Tt(a){const v=a.target;v.removeEventListener("dispose",Tt),Yr(v)}function Yr(a){Kr(a),U.remove(a)}function Kr(a){const v=U.get(a).programs;v!==void 0&&(v.forEach(function(y){re.releaseProgram(y)}),a.isShaderMaterial&&re.releaseShaderCache(a))}this.renderBufferDirect=function(a,v,y,b,C,de){v===null&&(v=ht);const he=C.isMesh&&C.matrixWorld.determinantAffine()<0,fe=$r(a,v,y,b,C);r.setMaterial(b,he);let _e=y.index,Se=1;if(b.wireframe===!0){if(_e=B.getWireframeAttribute(y),_e===void 0)return;Se=2}const Pe=y.drawRange,De=y.attributes.position;let ge=Pe.start*Se,He=(Pe.start+Pe.count)*Se;de!==null&&(ge=Math.max(ge,de.start*Se),He=Math.min(He,(de.start+de.count)*Se)),_e!==null?(ge=Math.max(ge,0),He=Math.min(He,_e.count)):De!=null&&(ge=Math.max(ge,0),He=Math.min(He,De.count));const ot=He-ge;if(ot<0||ot===1/0)return;ue.setup(C,b,fe,y,_e);let Qe,Ye=oe;if(_e!==null&&(Qe=ie.get(_e),Ye=k,Ye.setIndex(Qe)),C.isMesh)b.wireframe===!0?(r.setLineWidth(b.wireframeLinewidth*at()),Ye.setMode(x.LINES)):Ye.setMode(x.TRIANGLES);else if(C.isLine){let ut=b.linewidth;ut===void 0&&(ut=1),r.setLineWidth(ut*at()),C.isLineSegments?Ye.setMode(x.LINES):C.isLineLoop?Ye.setMode(x.LINE_LOOP):Ye.setMode(x.LINE_STRIP)}else C.isPoints?Ye.setMode(x.POINTS):C.isSprite&&Ye.setMode(x.TRIANGLES);if(C.isBatchedMesh)if(Ve.get("WEBGL_multi_draw"))Ye.renderMultiDraw(C._multiDrawStarts,C._multiDrawCounts,C._multiDrawCount);else{const ut=C._multiDrawStarts,pe=C._multiDrawCounts,pt=C._multiDrawCount,Oe=_e?ie.get(_e).bytesPerElement:1,Et=U.get(b).currentProgram.getUniforms();for(let At=0;At<pt;At++)Et.setValue(x,"_gl_DrawID",At),Ye.render(ut[At]/Oe,pe[At])}else if(C.isInstancedMesh)Ye.renderInstances(ge,ot,C.count);else if(y.isInstancedBufferGeometry){const ut=y._maxInstanceCount!==void 0?y._maxInstanceCount:1/0,pe=Math.min(y.instanceCount,ut);Ye.renderInstances(ge,ot,pe)}else Ye.render(ge,ot)};function Qn(a,v,y,b){G!==null&&a.isNodeMaterial&&G.setObject(b,a),Be===!0&&Me.setState(a,y,!1),a.transparent===!0&&a.side===Lt&&a.forceSinglePass===!1?(a.side=St,a.needsUpdate=!0,dn(a,v,b),a.side=sn,a.needsUpdate=!0,dn(a,v,b),a.side=Lt):dn(a,v,b)}this.compile=function(a,v,y=null){y===null&&(y=a),G!==null&&G.renderStart(a,v,y),m=ae.get(y),m.init(v),c.push(m),y.traverseVisible(function(C){C.isLight&&C.layers.test(v.layers)&&(m.pushLight(C),C.castShadow&&m.pushShadow(C))}),a!==y&&a.traverseVisible(function(C){C.isLight&&C.layers.test(v.layers)&&(m.pushLight(C),C.castShadow&&m.pushShadow(C))}),m.setupLights(),G!==null&&G.updateLights(m.state.lightsArray),Ke=this.localClippingEnabled,Be=Me.init(this.clippingPlanes,Ke),Be===!0&&Me.setGlobalState(this.clippingPlanes,v),G!==null&&Ae.render(m.state.shadowsArray,y,v);const b=new Set;return a.traverse(function(C){if(!(C.isMesh||C.isPoints||C.isLine||C.isSprite))return;const de=C.material;if(de)if(Array.isArray(de))for(let he=0;he<de.length;he++){const fe=de[he];Qn(fe,y,v,C),b.add(fe)}else Qn(de,y,v,C),b.add(de)}),m=c.pop(),G!==null&&G.renderEnd(),b},this.compileAsync=function(a,v,y=null){const b=this.compile(a,v,y);return new Promise(C=>{function de(){if(b.forEach(function(he){const _e=U.get(he).currentProgram;(_e===void 0||_e.isReady())&&b.delete(he)}),b.size===0){C(a);return}setTimeout(de,10)}Ve.get("KHR_parallel_shader_compile")!==null?de():setTimeout(de,10)})};let Rn=null;function qr(a){Rn&&Rn(a)}function Jn(){Gt.stop()}function jn(){Gt.start()}const Gt=new Br;Gt.setAnimationLoop(qr),typeof self<"u"&&Gt.setContext(self),this.setAnimationLoop=function(a){Rn=a,ve.setAnimationLoop(a),a===null?Gt.stop():Gt.start()},ve.addEventListener("sessionstart",Jn),ve.addEventListener("sessionend",jn),this.render=function(a,v){if(v!==void 0&&v.isCamera!==!0){Je("WebGLRenderer.render: camera is not an instance of THREE.Camera.");return}if(F===!0)return;G!==null&&G.renderStart(a,v);const y=ve.enabled===!0&&ve.isPresenting===!0,b=_!==null&&(ne===null||y)&&_.begin(D,ne);if(a.matrixWorldAutoUpdate===!0&&a.updateMatrixWorld(),v.parent===null&&v.matrixWorldAutoUpdate===!0&&v.updateMatrixWorld(),ve.enabled===!0&&ve.isPresenting===!0&&(_===null||_.isCompositing()===!1)&&(ve.cameraAutoUpdate===!0&&ve.updateCamera(v),v=ve.getCamera()),a.isScene===!0&&a.onBeforeRender(D,a,v,ne),m=ae.get(a,c.length),m.init(v),m.state.textureUnits=O.getTextureUnits(),c.push(m),Ie.multiplyMatrices(v.projectionMatrix,v.matrixWorldInverse),we.setFromProjectionMatrix(Ie,li,v.reversedDepth),Ke=this.localClippingEnabled,Be=Me.init(this.clippingPlanes,Ke),S=le.get(a,w.length),S.init(),w.push(S),ve.enabled===!0&&ve.isPresenting===!0){const he=D.xr.getDepthSensingMesh();he!==null&&bn(he,v,-1/0,D.sortObjects)}bn(a,v,0,D.sortObjects),S.finish(),G!==null&&G.updateLights(m.state.lightsArray),D.sortObjects===!0&&S.sort(Ee,Ue),tt=ve.enabled===!1||ve.isPresenting===!1||ve.hasDepthSensing()===!1,tt&&Ce.addToRenderList(S,a),this.info.render.frame++,this.info.autoReset===!0&&this.info.reset(),Be===!0&&Me.beginShadows();const C=m.state.shadowsArray;if(Ae.render(C,a,v),Be===!0&&Me.endShadows(),(b&&_.hasRenderPass())===!1){const he=S.opaque,fe=S.transmissive;if(m.setupLights(),v.isArrayCamera){const _e=v.cameras;if(fe.length>0)for(let Se=0,Pe=_e.length;Se<Pe;Se++){const De=_e[Se];ti(he,fe,a,De)}tt&&Ce.render(a);for(let Se=0,Pe=_e.length;Se<Pe;Se++){const De=_e[Se];ei(S,a,De,De.viewport)}}else fe.length>0&&ti(he,fe,a,v),tt&&Ce.render(a),ei(S,a,v)}ne!==null&&K===0&&(O.updateMultisampleRenderTarget(ne),O.updateRenderTargetMipmap(ne)),b&&_.end(D),a.isScene===!0&&a.onAfterRender(D,a,v),ue.resetDefaultState(),Z=-1,j=null,c.pop(),c.length>0?(m=c[c.length-1],O.setTextureUnits(m.state.textureUnits),Be===!0&&Me.setGlobalState(D.clippingPlanes,m.state.camera)):m=null,w.pop(),w.length>0?S=w[w.length-1]:S=null,G!==null&&G.renderEnd()};function bn(a,v,y,b){if(a.visible===!1)return;if(a.layers.test(v.layers)){if(a.isGroup)y=a.renderOrder;else if(a.isLOD)a.autoUpdate===!0&&a.update(v);else if(a.isLightProbeGrid)m.pushLightProbeGrid(a);else if(a.isLight)m.pushLight(a),a.castShadow&&m.pushShadow(a);else if(a.isSprite){if(!a.frustumCulled||a.intersectsFrustum(we)){b&&ft.setFromMatrixPosition(a.matrixWorld).applyMatrix4(Ie);const he=X.update(a),fe=a.material;fe.visible&&S.push(a,he,fe,y,ft.z,null,v)}}else if((a.isMesh||a.isLine||a.isPoints)&&(!a.frustumCulled||a.intersectsFrustum(we))){const he=X.update(a),fe=a.material;if(b&&(a.boundingSphere!==void 0?(a.boundingSphere===null&&a.computeBoundingSphere(),ft.copy(a.boundingSphere.center)):(he.boundingSphere===null&&he.computeBoundingSphere(),ft.copy(he.boundingSphere.center)),ft.applyMatrix4(a.matrixWorld).applyMatrix4(Ie)),Array.isArray(fe)){const _e=he.groups;for(let Se=0,Pe=_e.length;Se<Pe;Se++){const De=_e[Se],ge=fe[De.materialIndex];ge&&ge.visible&&S.push(a,he,ge,y,ft.z,De,v)}}else fe.visible&&S.push(a,he,fe,y,ft.z,null,v)}}const de=a.children;for(let he=0,fe=de.length;he<fe;he++)bn(de[he],v,y,b)}function ei(a,v,y,b){const{opaque:C,transmissive:de,transparent:he}=a;m.setupLightsView(y),Be===!0&&Me.setGlobalState(D.clippingPlanes,y),b&&r.viewport(ee.copy(b)),C.length>0&&fn(C,v,y),de.length>0&&fn(de,v,y),he.length>0&&fn(he,v,y),r.buffers.depth.setTest(!0),r.buffers.depth.setMask(!0),r.buffers.color.setMask(!0),r.setPolygonOffset(!1)}function ti(a,v,y,b){if((y.isScene===!0?y.overrideMaterial:null)!==null)return;if(m.state.transmissionRenderTarget[b.id]===void 0){const ge=Ve.has("EXT_color_buffer_half_float")||Ve.has("EXT_color_buffer_float");m.state.transmissionRenderTarget[b.id]=new Mt(1,1,{generateMipmaps:!0,type:ge?Dt:Ct,minFilter:Kt,samples:Math.max(4,u.samples),stencilBuffer:o,resolveDepthBuffer:!1,resolveStencilBuffer:!1,storeMultisampledDepthBuffer:!1,storeMultisampledStencilBuffer:!1,colorSpace:nt.workingColorSpace})}const de=m.state.transmissionRenderTarget[b.id],he=b.viewport||ee;de.setSize(he.z*D.transmissionResolutionScale,he.w*D.transmissionResolutionScale);const fe=D.getRenderTarget(),_e=D.getActiveCubeFace(),Se=D.getActiveMipmapLevel();D.setRenderTarget(de),D.getClearColor(it),ke=D.getClearAlpha(),ke<1&&D.setClearColor(16777215,.5),D.clear(),tt&&Ce.render(y);const Pe=D.toneMapping;D.toneMapping=Pt;const De=b.viewport;if(b.viewport!==void 0&&(b.viewport=void 0),m.setupLightsView(b),Be===!0&&Me.setGlobalState(D.clippingPlanes,b),fn(a,y,b),O.updateMultisampleRenderTarget(de),O.updateRenderTargetMipmap(de),Ve.has("WEBGL_multisampled_render_to_texture")===!1){let ge=!1;for(let He=0,ot=v.length;He<ot;He++){const Qe=v[He],{object:Ye,geometry:ut,material:pe,group:pt}=Qe;if(pe.side===Lt&&Ye.layers.test(b.layers)){const Oe=pe.side;pe.side=St,pe.needsUpdate=!0,ni(Ye,y,b,ut,pe,pt),pe.side=Oe,pe.needsUpdate=!0,ge=!0}}ge===!0&&(O.updateMultisampleRenderTarget(de),O.updateRenderTargetMipmap(de))}D.setRenderTarget(fe,_e,Se),D.setClearColor(it,ke),De!==void 0&&(b.viewport=De),D.toneMapping=Pe}function fn(a,v,y){const b=v.isScene===!0?v.overrideMaterial:null;for(let C=0,de=a.length;C<de;C++){const he=a[C],{object:fe,geometry:_e,group:Se}=he;let Pe=he.material;Pe.allowOverride===!0&&b!==null&&(Pe=b),fe.layers.test(y.layers)&&ni(fe,v,y,_e,Pe,Se)}}function ni(a,v,y,b,C,de){G!==null&&C.isNodeMaterial&&G.setObject(a,C),a.onBeforeRender(D,v,y,b,C,de),a.modelViewMatrix.multiplyMatrices(y.matrixWorldInverse,a.matrixWorld),a.normalMatrix.getNormalMatrix(a.modelViewMatrix),C.onBeforeRender(D,v,y,b,a,de),C.transparent===!0&&C.side===Lt&&C.forceSinglePass===!1?(C.side=St,C.needsUpdate=!0,D.renderBufferDirect(y,v,b,C,a,de),C.side=sn,C.needsUpdate=!0,D.renderBufferDirect(y,v,b,C,a,de),C.side=Lt):D.renderBufferDirect(y,v,b,C,a,de),a.onAfterRender(D,v,y,b,C,de)}function dn(a,v,y){v.isScene!==!0&&(v=ht);const b=U.get(a),C=m.state.lights,de=m.state.shadowsArray,he=C.state.version,fe=re.getParameters(a,C.state,de,v,y,m.state.lightProbeGridArray),_e=re.getProgramCacheKey(fe);let Se=b.programs;b.environment=a.isMeshStandardMaterial||a.isMeshLambertMaterial||a.isMeshPhongMaterial?v.environment:null,b.fog=v.fog;const Pe=a.isMeshStandardMaterial||a.isMeshLambertMaterial&&!a.envMap||a.isMeshPhongMaterial&&!a.envMap;b.envMap=te.get(a.envMap||b.environment,Pe),b.envMapRotation=b.environment!==null&&a.envMap===null?v.environmentRotation:a.envMapRotation,Se===void 0&&(a.addEventListener("dispose",Tt),Se=new Map,b.programs=Se);let De=Se.get(_e);if(De!==void 0){if(b.currentProgram===De&&b.lightsStateVersion===he)return ri(a,fe),De}else fe.uniforms=re.getUniforms(a),G!==null&&a.isNodeMaterial&&G.build(a,y,fe),a.onBeforeCompile(fe,D),De=re.acquireProgram(fe,_e),Se.set(_e,De),b.uniforms=fe.uniforms;const ge=b.uniforms;return(!a.isShaderMaterial&&!a.isRawShaderMaterial||a.clipping===!0)&&(ge.clippingPlanes=Me.uniform),ri(a,fe),b.needsLights=Jr(a),b.lightsStateVersion=he,b.needsLights&&(ge.ambientLightColor.value=C.state.ambient,ge.lightProbe.value=C.state.probe,ge.sunLights.value=C.state.sun,ge.sunLightShadows.value=C.state.sunShadow,ge.directionalLights.value=C.state.directional,ge.directionalLightShadows.value=C.state.directionalShadow,ge.spotLights.value=C.state.spot,ge.spotLightShadows.value=C.state.spotShadow,ge.rectAreaLights.value=C.state.rectArea,ge.ltc_1.value=C.state.rectAreaLTC1,ge.ltc_2.value=C.state.rectAreaLTC2,ge.pointLights.value=C.state.point,ge.pointLightShadows.value=C.state.pointShadow,ge.hemisphereLights.value=C.state.hemi,ge.sunShadowMatrix.value=C.state.sunShadowMatrix,ge.sunShadowCascade.value=C.state.sunShadowCascade,ge.directionalShadowMatrix.value=C.state.directionalShadowMatrix,ge.spotLightMatrix.value=C.state.spotLightMatrix,ge.spotLightMap.value=C.state.spotLightMap,ge.pointShadowMatrix.value=C.state.pointShadowMatrix),b.lightProbeGrid=m.state.lightProbeGridArray.length>0,b.currentProgram=De,b.uniformsList=null,De}function ii(a){if(a.uniformsList===null){const v=a.currentProgram.getUniforms();a.uniformsList=vn.seqWithValue(v.seq,a.uniforms)}return a.uniformsList}function ri(a,v){const y=U.get(a);y.outputColorSpace=v.outputColorSpace,y.batching=v.batching,y.batchingColor=v.batchingColor,y.instancing=v.instancing,y.instancingColor=v.instancingColor,y.instancingMorph=v.instancingMorph,y.skinning=v.skinning,y.morphTargets=v.morphTargets,y.morphNormals=v.morphNormals,y.morphColors=v.morphColors,y.morphTargetsCount=v.morphTargetsCount,y.numClippingPlanes=v.numClippingPlanes,y.numIntersection=v.numClipIntersection,y.vertexAlphas=v.vertexAlphas,y.vertexTangents=v.vertexTangents,y.toneMapping=v.toneMapping}function Zr(a,v){if(a.length===0)return null;if(a.length===1)return a[0].texture!==null?a[0]:null;h.setFromMatrixPosition(v.matrixWorld);for(let y=0,b=a.length;y<b;y++){const C=a[y];if(C.texture!==null&&C.boundingBox.containsPoint(h))return C}return null}function $r(a,v,y,b,C){v.isScene!==!0&&(v=ht),O.resetTextureUnits();const de=v.fog,he=b.isMeshStandardMaterial||b.isMeshLambertMaterial||b.isMeshPhongMaterial?v.environment:null,fe=ne===null?D.outputColorSpace:ne.isXRRenderTarget===!0?ne.texture.colorSpace:nt.workingColorSpace,_e=b.isMeshStandardMaterial||b.isMeshLambertMaterial&&!b.envMap||b.isMeshPhongMaterial&&!b.envMap,Se=te.get(b.envMap||he,_e),Pe=b.vertexColors===!0&&!!y.attributes.color&&y.attributes.color.itemSize===4,De=!!y.attributes.tangent&&(!!b.normalMap||b.anisotropy>0),ge=!!y.morphAttributes.position,He=!!y.morphAttributes.normal,ot=!!y.morphAttributes.color;let Qe=Pt;b.toneMapped&&(ne===null||ne.isXRRenderTarget===!0)&&(Qe=D.toneMapping);const Ye=y.morphAttributes.position||y.morphAttributes.normal||y.morphAttributes.color,ut=Ye!==void 0?Ye.length:0,pe=U.get(b),pt=m.state.lights;if(Be===!0&&(Ke===!0||a!==j)){const Ze=a===j&&b.id===Z;Me.setState(b,a,Ze)}let Oe=!1;b.version===pe.__version?(pe.needsLights&&pe.lightsStateVersion!==pt.state.version||pe.outputColorSpace!==fe||C.isBatchedMesh&&pe.batching===!1||!C.isBatchedMesh&&pe.batching===!0||C.isBatchedMesh&&pe.batchingColor===!0&&C._colorsTexture===null||C.isBatchedMesh&&pe.batchingColor===!1&&C._colorsTexture!==null||C.isInstancedMesh&&pe.instancing===!1||!C.isInstancedMesh&&pe.instancing===!0||C.isSkinnedMesh&&pe.skinning===!1||!C.isSkinnedMesh&&pe.skinning===!0||C.isInstancedMesh&&pe.instancingColor===!0&&C.instanceColor===null||C.isInstancedMesh&&pe.instancingColor===!1&&C.instanceColor!==null||C.isInstancedMesh&&pe.instancingMorph===!0&&C.morphTexture===null||C.isInstancedMesh&&pe.instancingMorph===!1&&C.morphTexture!==null||pe.envMap!==Se||b.fog===!0&&pe.fog!==de||pe.numClippingPlanes!==void 0&&(pe.numClippingPlanes!==Me.numPlanes||pe.numIntersection!==Me.numIntersection)||pe.vertexAlphas!==Pe||pe.vertexTangents!==De||pe.morphTargets!==ge||pe.morphNormals!==He||pe.morphColors!==ot||pe.toneMapping!==Qe||pe.morphTargetsCount!==ut||!!pe.lightProbeGrid!=m.state.lightProbeGridArray.length>0)&&(Oe=!0):(Oe=!0,pe.__version=b.version);let Et=pe.currentProgram;Oe===!0&&(Et=dn(b,v,C),G&&b.isNodeMaterial&&G.onUpdateProgram(b,Et,pe));let At=!1,yt=!1,kt=!1;const Xe=Et.getUniforms(),rt=pe.uniforms;if(r.useProgram(Et.program)&&(At=!0,yt=!0,kt=!0),b.id!==Z&&(Z=b.id,yt=!0),pe.needsLights){const Ze=Zr(m.state.lightProbeGridArray,C);pe.lightProbeGrid!==Ze&&(pe.lightProbeGrid=Ze,yt=!0)}if(At||j!==a){r.buffers.depth.getReversed()&&a.reversedDepth!==!0&&(a._reversedDepth=!0,a.updateProjectionMatrix()),Xe.setValue(x,"projectionMatrix",a.projectionMatrix),Xe.setValue(x,"viewMatrix",a.matrixWorldInverse);const Ot=Xe.map.cameraPosition;Ot!==void 0&&Ot.setValue(x,je.setFromMatrixPosition(a.matrixWorld)),u.logarithmicDepthBuffer&&Xe.setValue(x,"logDepthBufFC",2/(Math.log(a.far+1)/Math.LN2)),(b.isMeshPhongMaterial||b.isMeshToonMaterial||b.isMeshLambertMaterial||b.isMeshBasicMaterial||b.isMeshStandardMaterial||b.isShaderMaterial)&&Xe.setValue(x,"isOrthographic",a.isOrthographicCamera===!0),j!==a&&(j=a,yt=!0,kt=!0)}if(pe.needsLights&&(pt.state.sunShadowMap.length>0&&Xe.setValue(x,"sunShadowMap",pt.state.sunShadowMap,O),pt.state.directionalShadowMap.length>0&&Xe.setValue(x,"directionalShadowMap",pt.state.directionalShadowMap,O),pt.state.spotShadowMap.length>0&&Xe.setValue(x,"spotShadowMap",pt.state.spotShadowMap,O),pt.state.pointShadowMap.length>0&&Xe.setValue(x,"pointShadowMap",pt.state.pointShadowMap,O)),C.isSkinnedMesh){Xe.setOptional(x,C,"bindMatrix"),Xe.setOptional(x,C,"bindMatrixInverse");const Ze=C.skeleton;Ze&&(Ze.boneTexture===null&&Ze.computeBoneTexture(),Xe.setValue(x,"boneTexture",Ze.boneTexture,O))}C.isBatchedMesh&&(Xe.setOptional(x,C,"batchingTexture"),Xe.setValue(x,"batchingTexture",C._matricesTexture,O),Xe.setOptional(x,C,"batchingIdTexture"),Xe.setValue(x,"batchingIdTexture",C._indirectTexture,O),Xe.setOptional(x,C,"batchingColorTexture"),C._colorsTexture!==null&&Xe.setValue(x,"batchingColorTexture",C._colorsTexture,O));const Ft=y.morphAttributes;if((Ft.position!==void 0||Ft.normal!==void 0||Ft.color!==void 0)&&E.update(C,y,Et),(yt||pe.receiveShadow!==C.receiveShadow)&&(pe.receiveShadow=C.receiveShadow,Xe.setValue(x,"receiveShadow",C.receiveShadow)),(b.isMeshStandardMaterial||b.isMeshLambertMaterial||b.isMeshPhongMaterial)&&b.envMap===null&&v.environment!==null&&(rt.envMapIntensity.value=v.environmentIntensity),rt.dfgLUT!==void 0&&(rt.dfgLUT.value=_d()),yt){if(Xe.setValue(x,"toneMappingExposure",D.toneMappingExposure),pe.needsLights&&Qr(rt,kt),de&&b.fog===!0&&xe.refreshFogUniforms(rt,de),xe.refreshMaterialUniforms(rt,b,$,V,m.state.transmissionRenderTarget[a.id]),pe.needsLights&&pe.lightProbeGrid){const Ze=pe.lightProbeGrid;rt.probesSH.value=Ze.texture,rt.probesMin.value.copy(Ze.boundingBox.min),rt.probesMax.value.copy(Ze.boundingBox.max),rt.probesResolution.value.copy(Ze.resolution)}vn.upload(x,ii(pe),rt,O)}if(b.isShaderMaterial&&b.uniformsNeedUpdate===!0&&(vn.upload(x,ii(pe),rt,O),b.uniformsNeedUpdate=!1),b.isSpriteMaterial&&Xe.setValue(x,"center",C.center),Xe.setValue(x,"modelViewMatrix",C.modelViewMatrix),Xe.setValue(x,"normalMatrix",C.normalMatrix),Xe.setValue(x,"modelMatrix",C.matrixWorld),b.uniformsGroups!==void 0){const Ze=b.uniformsGroups;for(let Ot=0,zt=Ze.length;Ot<zt;Ot++){const oi=Ze[Ot];J.update(oi,Et),J.bind(oi,Et)}}return Et}function Qr(a,v){a.ambientLightColor.needsUpdate=v,a.lightProbe.needsUpdate=v,a.sunLights.needsUpdate=v,a.sunLightShadows.needsUpdate=v,a.directionalLights.needsUpdate=v,a.directionalLightShadows.needsUpdate=v,a.pointLights.needsUpdate=v,a.pointLightShadows.needsUpdate=v,a.spotLights.needsUpdate=v,a.spotLightShadows.needsUpdate=v,a.rectAreaLights.needsUpdate=v,a.hemisphereLights.needsUpdate=v}function Jr(a){return a.isMeshLambertMaterial||a.isMeshToonMaterial||a.isMeshPhongMaterial||a.isMeshStandardMaterial||a.isShadowMaterial||a.isShaderMaterial&&a.lights===!0}this.getActiveCubeFace=function(){return Q},this.getActiveMipmapLevel=function(){return K},this.getRenderTarget=function(){return ne},this.setRenderTargetTextures=function(a,v,y){const b=U.get(a);b.__autoAllocateDepthBuffer=a.resolveDepthBuffer===!1,b.__autoAllocateDepthBuffer===!1&&(b.__useRenderToTexture=!1),U.get(a.texture).__webglTexture=v,U.get(a.depthTexture).__webglTexture=b.__autoAllocateDepthBuffer?void 0:y,b.__hasExternalTextures=!0},this.setRenderTargetFramebuffer=function(a,v){const y=U.get(a);y.__webglFramebuffer=v,y.__useDefaultFramebuffer=v===void 0},this.setRenderTarget=function(a,v=0,y=0){ne=a,Q=v,K=y;let b=null,C=!1,de=!1;if(a){const fe=U.get(a);if(fe.__useDefaultFramebuffer!==void 0){r.bindFramebuffer(x.FRAMEBUFFER,fe.__webglFramebuffer),ee.copy(a.viewport),be.copy(a.scissor),Re=a.scissorTest,r.viewport(ee),r.scissor(be),r.setScissorTest(Re),Z=-1;return}else if(fe.__webglFramebuffer===void 0)O.setupRenderTarget(a);else if(fe.__hasExternalTextures)O.rebindTextures(a,U.get(a.texture).__webglTexture,U.get(a.depthTexture).__webglTexture);else if(a.depthBuffer){const Pe=a.depthTexture;if(fe.__boundDepthTexture!==Pe){if(Pe!==null&&U.has(Pe)&&(a.width!==Pe.image.width||a.height!==Pe.image.height))throw new Error("THREE.WebGLRenderer: Attached DepthTexture is initialized to the incorrect size.");O.setupDepthRenderbuffer(a)}}const _e=a.texture;(_e.isData3DTexture||_e.isDataArrayTexture||_e.isCompressedArrayTexture)&&(de=!0);const Se=U.get(a).__webglFramebuffer;a.isWebGLCubeRenderTarget?(Array.isArray(Se[v])?b=Se[v][y]:b=Se[v],C=!0):a.samples>0&&O.useMultisampledRTT(a)===!1?b=U.get(a).__webglMultisampledFramebuffer:Array.isArray(Se)?b=Se[y]:b=Se,ee.copy(a.viewport),be.copy(a.scissor),Re=a.scissorTest}else ee.copy(me).multiplyScalar($).floor(),be.copy(ye).multiplyScalar($).floor(),Re=st;if(y!==0&&(b=q),r.bindFramebuffer(x.FRAMEBUFFER,b)&&r.drawBuffers(a,b),r.viewport(ee),r.scissor(be),r.setScissorTest(Re),C){const fe=U.get(a.texture);x.framebufferTexture2D(x.FRAMEBUFFER,x.COLOR_ATTACHMENT0,x.TEXTURE_CUBE_MAP_POSITIVE_X+v,fe.__webglTexture,y)}else if(de){const fe=v;for(let _e=0;_e<a.textures.length;_e++){const Se=U.get(a.textures[_e]);x.framebufferTextureLayer(x.FRAMEBUFFER,x.COLOR_ATTACHMENT0+_e,Se.__webglTexture,y,fe)}}else if(a!==null&&y!==0){const fe=U.get(a.texture);x.framebufferTexture2D(x.FRAMEBUFFER,x.COLOR_ATTACHMENT0,x.TEXTURE_2D,fe.__webglTexture,y)}Z=-1};function ai(a){const v=U.get(a);return(v.__readFormat!==a.format||v.__readType!==a.type)&&(v.__readFormat=a.format,v.__readType=a.type,v.__formatReadable=u.textureFormatReadable(a.format),v.__typeReadable=u.textureTypeReadable(a.type)),v}this.readRenderTargetPixels=function(a,v,y,b,C,de,he,fe=0){if(!(a&&a.isWebGLRenderTarget)){Je("WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.");return}let _e=U.get(a).__webglFramebuffer;if(a.isWebGLCubeRenderTarget&&he!==void 0&&(_e=_e[he]),_e){r.bindFramebuffer(x.FRAMEBUFFER,_e);try{const Se=a.textures[fe],Pe=Se.format,De=Se.type;a.textures.length>1&&x.readBuffer(x.COLOR_ATTACHMENT0+fe);const ge=ai(Se);if(ge.__formatReadable===!1){Je("WebGLRenderer.readRenderTargetPixels: renderTarget is not in RGBA or implementation defined format.");return}if(ge.__typeReadable===!1){Je("WebGLRenderer.readRenderTargetPixels: renderTarget is not in UnsignedByteType or implementation defined type.");return}v>=0&&v<=a.width-b&&y>=0&&y<=a.height-C&&x.readPixels(v,y,b,C,se.convert(Pe),se.convert(De),de)}finally{const Se=ne!==null?U.get(ne).__webglFramebuffer:null;r.bindFramebuffer(x.FRAMEBUFFER,Se)}}},this.readRenderTargetPixelsAsync=async function(a,v,y,b,C,de,he,fe=0){if(!(a&&a.isWebGLRenderTarget))throw new Error("THREE.WebGLRenderer.readRenderTargetPixels: renderTarget is not THREE.WebGLRenderTarget.");let _e=U.get(a).__webglFramebuffer;if(a.isWebGLCubeRenderTarget&&he!==void 0&&(_e=_e[he]),_e)if(v>=0&&v<=a.width-b&&y>=0&&y<=a.height-C){r.bindFramebuffer(x.FRAMEBUFFER,_e);const Se=a.textures[fe],Pe=Se.format,De=Se.type;a.textures.length>1&&x.readBuffer(x.COLOR_ATTACHMENT0+fe);const ge=ai(Se);if(ge.__formatReadable===!1)throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in RGBA or implementation defined format.");if(ge.__typeReadable===!1)throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: renderTarget is not in UnsignedByteType or implementation defined type.");const He=x.createBuffer();x.bindBuffer(x.PIXEL_PACK_BUFFER,He),x.bufferData(x.PIXEL_PACK_BUFFER,de.byteLength,x.STREAM_READ),x.readPixels(v,y,b,C,se.convert(Pe),se.convert(De),0),x.bindBuffer(x.PIXEL_PACK_BUFFER,null);const ot=ne!==null?U.get(ne).__webglFramebuffer:null;r.bindFramebuffer(x.FRAMEBUFFER,ot);const Qe=x.fenceSync(x.SYNC_GPU_COMMANDS_COMPLETE,0);return x.flush(),await na(x,Qe,4),x.bindBuffer(x.PIXEL_PACK_BUFFER,He),x.getBufferSubData(x.PIXEL_PACK_BUFFER,0,de),x.bindBuffer(x.PIXEL_PACK_BUFFER,null),x.deleteBuffer(He),x.deleteSync(Qe),de}else throw new Error("THREE.WebGLRenderer.readRenderTargetPixelsAsync: requested read bounds are out of range.")},this.copyFramebufferToTexture=function(a,v=null,y=0){const b=Math.pow(2,-y),C=Math.floor(a.image.width*b),de=Math.floor(a.image.height*b),he=v!==null?v.x:0,fe=v!==null?v.y:0;O.setTexture2D(a,0),x.copyTexSubImage2D(x.TEXTURE_2D,y,0,0,he,fe,C,de),r.unbindTexture()},this.copyTextureToTexture=function(a,v,y=null,b=null,C=0,de=0){let he,fe,_e,Se,Pe,De,ge,He,ot;const Qe=a.isCompressedTexture?a.mipmaps[de]:a.image;if(y!==null)he=y.max.x-y.min.x,fe=y.max.y-y.min.y,_e=y.isBox3?y.max.z-y.min.z:1,Se=y.min.x,Pe=y.min.y,De=y.isBox3?y.min.z:0;else{const rt=Math.pow(2,-C);he=Math.floor(Qe.width*rt),fe=Math.floor(Qe.height*rt),a.isDataArrayTexture?_e=Qe.depth:a.isData3DTexture?_e=Math.floor(Qe.depth*rt):_e=1,Se=0,Pe=0,De=0}b!==null?(ge=b.x,He=b.y,ot=b.z):(ge=0,He=0,ot=0);const Ye=se.convert(v.format),ut=se.convert(v.type);let pe;v.isData3DTexture?(O.setTexture3D(v,0),pe=x.TEXTURE_3D):v.isDataArrayTexture||v.isCompressedArrayTexture?(O.setTexture2DArray(v,0),pe=x.TEXTURE_2D_ARRAY):(O.setTexture2D(v,0),pe=x.TEXTURE_2D),r.activeTexture(x.TEXTURE0),r.pixelStorei(x.UNPACK_FLIP_Y_WEBGL,v.flipY),r.pixelStorei(x.UNPACK_PREMULTIPLY_ALPHA_WEBGL,v.premultiplyAlpha),r.pixelStorei(x.UNPACK_ALIGNMENT,v.unpackAlignment);const pt=r.getParameter(x.UNPACK_ROW_LENGTH),Oe=r.getParameter(x.UNPACK_IMAGE_HEIGHT),Et=r.getParameter(x.UNPACK_SKIP_PIXELS),At=r.getParameter(x.UNPACK_SKIP_ROWS),yt=r.getParameter(x.UNPACK_SKIP_IMAGES);r.pixelStorei(x.UNPACK_ROW_LENGTH,Qe.width),r.pixelStorei(x.UNPACK_IMAGE_HEIGHT,Qe.height),r.pixelStorei(x.UNPACK_SKIP_PIXELS,Se),r.pixelStorei(x.UNPACK_SKIP_ROWS,Pe),r.pixelStorei(x.UNPACK_SKIP_IMAGES,De);const kt=a.isDataArrayTexture||a.isData3DTexture,Xe=v.isDataArrayTexture||v.isData3DTexture;if(a.isDepthTexture){const rt=U.get(a),Ft=U.get(v),Ze=U.get(rt.__renderTarget),Ot=U.get(Ft.__renderTarget);r.bindFramebuffer(x.READ_FRAMEBUFFER,Ze.__webglFramebuffer),r.bindFramebuffer(x.DRAW_FRAMEBUFFER,Ot.__webglFramebuffer);for(let zt=0;zt<_e;zt++)kt&&(x.framebufferTextureLayer(x.READ_FRAMEBUFFER,x.COLOR_ATTACHMENT0,U.get(a).__webglTexture,C,De+zt),x.framebufferTextureLayer(x.DRAW_FRAMEBUFFER,x.COLOR_ATTACHMENT0,U.get(v).__webglTexture,de,ot+zt)),x.blitFramebuffer(Se,Pe,he,fe,ge,He,he,fe,x.DEPTH_BUFFER_BIT,x.NEAREST);r.bindFramebuffer(x.READ_FRAMEBUFFER,null),r.bindFramebuffer(x.DRAW_FRAMEBUFFER,null)}else if(C!==0||a.isRenderTargetTexture||U.has(a)){const rt=U.get(a),Ft=U.get(v);r.bindFramebuffer(x.READ_FRAMEBUFFER,P),r.bindFramebuffer(x.DRAW_FRAMEBUFFER,Y);for(let Ze=0;Ze<_e;Ze++)kt?x.framebufferTextureLayer(x.READ_FRAMEBUFFER,x.COLOR_ATTACHMENT0,rt.__webglTexture,C,De+Ze):x.framebufferTexture2D(x.READ_FRAMEBUFFER,x.COLOR_ATTACHMENT0,x.TEXTURE_2D,rt.__webglTexture,C),Xe?x.framebufferTextureLayer(x.DRAW_FRAMEBUFFER,x.COLOR_ATTACHMENT0,Ft.__webglTexture,de,ot+Ze):x.framebufferTexture2D(x.DRAW_FRAMEBUFFER,x.COLOR_ATTACHMENT0,x.TEXTURE_2D,Ft.__webglTexture,de),C!==0?x.blitFramebuffer(Se,Pe,he,fe,ge,He,he,fe,x.COLOR_BUFFER_BIT,x.NEAREST):Xe?x.copyTexSubImage3D(pe,de,ge,He,ot+Ze,Se,Pe,he,fe):x.copyTexSubImage2D(pe,de,ge,He,Se,Pe,he,fe);r.bindFramebuffer(x.READ_FRAMEBUFFER,null),r.bindFramebuffer(x.DRAW_FRAMEBUFFER,null)}else Xe?a.isDataTexture||a.isData3DTexture?x.texSubImage3D(pe,de,ge,He,ot,he,fe,_e,Ye,ut,Qe.data):v.isCompressedArrayTexture?x.compressedTexSubImage3D(pe,de,ge,He,ot,he,fe,_e,Ye,Qe.data):x.texSubImage3D(pe,de,ge,He,ot,he,fe,_e,Ye,ut,Qe):a.isDataTexture?x.texSubImage2D(x.TEXTURE_2D,de,ge,He,he,fe,Ye,ut,Qe.data):a.isCompressedTexture?x.compressedTexSubImage2D(x.TEXTURE_2D,de,ge,He,Qe.width,Qe.height,Ye,Qe.data):x.texSubImage2D(x.TEXTURE_2D,de,ge,He,he,fe,Ye,ut,Qe);r.pixelStorei(x.UNPACK_ROW_LENGTH,pt),r.pixelStorei(x.UNPACK_IMAGE_HEIGHT,Oe),r.pixelStorei(x.UNPACK_SKIP_PIXELS,Et),r.pixelStorei(x.UNPACK_SKIP_ROWS,At),r.pixelStorei(x.UNPACK_SKIP_IMAGES,yt),de===0&&v.generateMipmaps&&x.generateMipmap(pe),r.unbindTexture()},this.initRenderTarget=function(a){U.get(a).__webglFramebuffer===void 0&&O.setupRenderTarget(a)},this.initTexture=function(a){a.isCubeTexture?O.setTextureCube(a,0):a.isData3DTexture?O.setTexture3D(a,0):a.isDataArrayTexture||a.isCompressedArrayTexture?O.setTexture2DArray(a,0):O.setTexture2D(a,0),r.unbindTexture()},this.resetState=function(){Q=0,K=0,ne=null,r.reset(),ue.reset()},typeof __THREE_DEVTOOLS__<"u"&&__THREE_DEVTOOLS__.dispatchEvent(new CustomEvent("observe",{detail:this}))}get coordinateSystem(){return li}get outputColorSpace(){return this._outputColorSpace}set outputColorSpace(n){this._outputColorSpace=n;const t=this.getContext();t.drawingBufferColorSpace=nt._getDrawingBufferColorSpace(n),t.unpackColorSpace=nt._getUnpackColorSpace()}}export{ce as U,vd as W};
