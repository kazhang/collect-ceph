#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "rjenkins.h"

int main(int argc, char **argv)
{
    if(argc < 4)
    {
        printf("usage: query num_of_pg num_of_obj prefix\n");
        exit(-1);
    }

    int num_of_pg = atoi(argv[1]);
    int num_of_obj = atoi(argv[2]);

    char str[64];
    int cnt[1024] = {0};
    int i;
    for(i = 0; i < num_of_obj; i++)
    {
        memset(str, 0, sizeof(str));
        sprintf(str,"%s.%016x", argv[3], i);
        unsigned pg = ceph_str_hash_rjenkins(str, strlen(str)) % 128;
        cnt[pg]++;
    }
    putchar('[');
    for(i = 0; i < num_of_pg; i++)
    {
        if(i) putchar(',');
        printf(" %d", cnt[i]);
    }
    putchar(']');
    return 0;
}
