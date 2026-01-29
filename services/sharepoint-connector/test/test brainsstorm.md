// File mocks
interface FileMock {
  	sharepoint: {
		id: string,
    },
  	unique: {
      	id: string,
    }
}

const file1: FileMock = {
  	sharepoint: {
		id: "abcd_1",
    },
  	unique: {
      	id: "cont_1",
    }
}

const file2: FileMock = {
  	sharepoint: {
		id: "abcd_2",
    },
  	unique: {
      	id: "cont_2",
    }
}

interface FolderMock {
  	sharepoint: {
		id: string,
    },
  	unique: {
      	id: string,
    }
}


// start by looking at mocked graphql client engines - if there is anything for the boilerplate and I just implement resolvers
// 

// mockDrive1 and other files/entities should have sharepointMock and uniqueMock (so both states)

describe('Content Ingestion', () => {
  describe('when syncing a pdf file', () => {
    it('sends correct mimeType to ContentUpsert', async () => {
      runSynchronisation({ // takes the state
        ...baseState,
        sharepoint: [
          ...baseState.sharepoint,
          {
              type: 'site',
              mock: mockSite1,
              libraries: [
                  {
                      type: 'drive',
                      mock: mockDrive1,
                      content: [
                          {
                              type: 'folder',
                              mock: {...mockFolder1, moderationStatus: 2},
                              children: [
								  {
                                      type: 'file',
                                      mock: mockFile2,
                                  },
                              ]
                          },
                          {
                              type: 'file',
                              mock: mockFile1,
                          },
                      ]
                  },
                  {
                      type: 'list',
                      mock: sitePagesMock,
                      pages: [
                          sitePage1,
                          sitePage2
                      ]
                  }
              ]
          }
        ],
        unique: [
          	...baseState.unique,
          	{
                type: 'scope',
                mock: mockSite1,
                children: [
                    {
                        type: 'scope',
                        mock: mockDrive1,
                        children: [
                            {
                                type: 'folder',
                                mock: mockFolder1,
                                children: [
                                    {
                                        type: 'file',
                                        mock: mockFile2,
                                    },
                                ]
                            },
                            {
                                type: 'file',
                                mock: mockFile1,
                            },
                        ]
                    },
                    {
                        type: 'scope',
                        mock: sitePagesMock,
                        children: [
                            sitePage1,
                            sitePage2
                        ]
                    }
                ]
          	}
        ]
      })

      // Query the ingestion GraphQL client mock directly
      const upserts = getGraphQLOperations(mockIngestionGraphqlClient, 'ContentUpsert');
      expect(upserts.length).toBeGreaterThan(0);

      // Find the upsert for our test file
      const testFileUpsert = upserts.find(
        (u) => u.variables?.input?.mimeType === 'application/pdf',
      );

      expect(testFileUpsert).toBeDefined();
      expect(testFileUpsert?.variables.input).toMatchObject({
        mimeType: 'application/pdf',
        title: 'test.pdf',
      });
    });
  });
})


// We need an simple implementation for some of the grahql mutation/queries
// The client will have an initial state which will be mutated by the requests
// also queries will actually do filtering









