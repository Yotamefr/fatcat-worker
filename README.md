# FatCat Worker
This is the FatCat Worker

This is the components that does most of the dirty work. It gets a notification from the server upon parsing and modifying the message, and runs a function corresponding to the queue. It can work with either a worker on a remote git repo, or with a worker directory locally. Please refer to [config-example.yml](config-example.yml) for a configuration example.

Don't forget to check [.env-example](.env-example) for a `.env` example.