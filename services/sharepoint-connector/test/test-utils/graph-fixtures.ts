export const createDriveItem = (id: string, name: string, options: { 
  mimeType?: string; 
  size?: number; 
  syncFlag?: boolean;
  driveId?: string;
} = {}) => {
  const { mimeType = 'application/pdf', size = 1024, syncFlag = true, driveId = 'drive-1' } = options;
  
  return {
    id,
    name,
    webUrl: `https://sharepoint.example.com/sites/TestSite/Documents/${name}`,
    size,
    file: { mimeType },
    lastModifiedDateTime: new Date().toISOString(),
    parentReference: {
      driveId,
      path: `/drives/${driveId}/root:/Documents`,
    },
    listItem: {
      fields: {
        FileLeafRef: name,
        SyncFlag: syncFlag,
      },
    },
  };
};

export const createPageItem = (id: string, title: string, syncFlag = true) => {
  return {
    id,
    webUrl: `https://sharepoint.example.com/sites/TestSite/SitePages/${title}.aspx`,
    fields: {
      Title: title,
      SyncFlag: syncFlag,
      FileLeafRef: `${title}.aspx`,
      _ModerationStatus: 0,
      CanvasContent1: '<div>Mock Page Content</div>',
    },
  };
};

export const createPermission = (id: string, email: string, type: 'user' | 'group' = 'user') => {
  const identity: any = type === 'user' 
    ? { user: { id: `id-${id}`, email, displayName: email } }
    : { 
        group: { id: `id-${id}`, displayName: email },
        siteUser: { loginName: `c:0o.c|federateddirectoryclaimprovider|id-${id}` } 
      };
    
  return {
    id,
    grantedToV2: identity,
  };
};
